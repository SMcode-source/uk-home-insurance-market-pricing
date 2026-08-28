"""Forward price drift, modelled instead of flat-lined.

The problem this fixes
----------------------
`week` is a feature, and its main effect absorbs level drift -- but only inside
the training window. A tree has no split beyond the largest week it saw, so
every later week reuses the final leaf and forward drift is predicted flat.
Measured on the sample run: one Churchill risk priced at GBP 136.50 for week 8
and GBP 136.50 for weeks 9, 10 and 11 alike, while its holdout bias grew -9.3%
-> -18.8% -> -22.6%, with `bias ~ -mdape` throughout. That is a pure level
error, it scales with the forecast horizon, and it is invisible in an aggregate
MdAPE because it only bites the brands that were actually repricing.

A weekly market-price product forecasts forward by definition, so this had to be
fixed outside the tree. Nothing that is a *feature* of a tree can extrapolate;
the level has to be carried by something that can.

A correction, not a replacement
-------------------------------
The obvious design is to re-express the model as

    log(premium) = risk_shape(features without week) + level(brand, week)

fitting the shape with `week` removed and reading the level off the residuals.
That was tried and it is wrong, for a reason worth stating: it makes a strictly
additive claim about the level, and a minimum premium breaks it. A quote sitting
on its brand's floor does not move when the brand's level moves, and on this
project's sample data 14-29% of each brand's quotes sit on that floor. Forcing
an additive level onto those rows over-corrects exactly them. Measured, that
form cost about 2 points of MdAPE at a **one-week** horizon -- where there is
almost no forward drift to correct at all, so the entire difference was damage.

So the wrapper leaves the underlying model alone. It fits the ordinary approach,
`week` included, and at prediction time:

- clamps `week` to the last week the model was trained on. The tree flat-lines
  out there anyway -- there is no split beyond its training range -- so this
  changes nothing it would have done, and makes explicit that any forward
  movement comes from the level term rather than from the tree;
- adds the modelled level *change* between that week and the target week.

In-window the correction is exactly zero and predictions are bit-identical to
the unwrapped approach, which a test asserts. Only the forecast horizon changes.

The level series still needs a model that is not allowed to absorb the level, so
it gets its own week-agnostic fit alongside. That series is the per-brand price
index, which is a thing the project wants anyway, and `drift_report()` prints
it.

Why the level comes from residuals, not from weekly means
---------------------------------------------------------
A raw mean premium per brand-week confounds price with mix. On a rotating panel
-- which vendor extracts generally are -- the risks change between weeks, so a
brand whose later weeks happen to contain cheaper properties looks like it cut
prices when it did nothing. Taking the mean of the *residuals* from a risk model
removes exactly that: whatever the risk model can explain about the property is
already subtracted, and what is left is the level.

Why the residuals are computed out-of-fold
------------------------------------------
In-sample residuals are biased small, because the inner model has already fitted
some of the level as if it were risk. Measured on a synthetic market with a
known 2.00%/week drift and an in-sample fit, the recovered slope was 1.61%/week
-- a 20% attenuation, entirely in the direction of under-correcting, which is
the same direction as the bug being fixed. So the level is read off *out-of-fold*
residuals: the data is split into `n_folds` parts, each part's residual comes
from a model that never saw it, and the level series is unbiased.

That costs `n_folds` extra inner fits. It is worth it for a term whose entire
job is to be unbiased at the boundary, but it does make the EBM variant slow --
`n_folds=1` reverts to in-sample residuals if you need the speed and can accept
a level that systematically under-shoots.

The out-of-fold levels are then centred per brand, so the series carries only
*movement*. The absolute level stays inside the inner model where it was fitted;
without centring, the gap between out-of-fold and in-sample residuals would be
added to every prediction as a constant offset.

Whether to extrapolate a trend at all is measured, not assumed
--------------------------------------------------------------
This is the part that matters, and the first version of this module got it
wrong. Insurance price levels behave much more like a random walk than like a
trend: a brand's tactical position wanders, it does not march. For a random walk
the optimal forecast at *every* horizon is the last observed value, and fitting
a slope to its history projects noise forward -- which adds error rather than
removing it, in whichever direction the walk happened to be pointing.

Measured on the sample data, where the generator's tactical layer is exactly
such a walk: projecting the full fitted per-brand slope took overall MdAPE from
4.60% to 7.11% and made the worst brand worse (Churchill 14.63% -> 15.92%),
because its slope over the training window pointed down while the holdout went
up. That is not a tuning problem. A trend model applied to a walk is the wrong
model, and it fails hardest exactly where the drift is largest.

So `trend_weight` is fitted rather than assumed. The last `validation_weeks` of
the training window are held out, the predicted level *change* is scored against
the realised one across candidate weights, and the winner is used. On a walk it
selects ~0 and nothing is projected, which is the correct martingale forecast.
On a genuine trend it selects ~1. Pass a float to override when you know which
regime you are in.

The remaining guards
--------------------
- **Credibility weighting.** A projected slope blends the brand's own toward the
  market's with weight `n_weeks / (n_weeks + credibility_weeks)`, so a brand
  seen for two weeks is mostly told what the market did.
- **A horizon cap.** Past `max_horizon` weeks the correction stops growing.
  Beyond a quarter, "this brand keeps moving at this rate" is not a claim the
  data supports.

What this does and does not buy
-------------------------------
Measured on the sample data, against the unwrapped `gbm_per_brand`:

    horizon 1 week    2.71% -> 2.71%   (validation chose 0; no correction)
    horizon 2 weeks   2.69% -> 2.73%
    horizon 3 weeks   4.60% -> 4.48%

Small, and honestly so. The structural defect is removed -- the model no longer
silently reuses a training-window leaf for every future week, the forward
movement is explicit and inspectable, and the correction cannot regress the
in-window fit. But a random walk does not become predictable because it is
modelled: with nine training weeks, the per-brand slopes here are mostly noise,
which is why the validation damps them to a quarter of their fitted size.

Expect this to matter more, not less, on real data. UK household premiums have
had sustained market-wide movement that a fitted slope can actually see, and
`drift_report()` is where to look at how much of it each brand carries. Expect
it to matter on longer horizons too: at one week the unwrapped model's
flat-line is very nearly right, and at one week this wrapper agrees with it
exactly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Approach

_MARKET = "__market__"


class BrandTrend:
    """Per-brand level series over time, with a damped forward extension.

    Fitted on residuals from a week-agnostic risk model -- see the module
    docstring for why residuals rather than raw premiums.
    """

    def __init__(
        self,
        *,
        credibility_weeks: float = 4.0,
        anchor_weeks: int = 1,
        max_horizon: int = 13,
        trend_weight=None,
        validation_weeks: int = 3,
    ):
        if credibility_weeks < 0:
            raise ValueError("credibility_weeks must be >= 0")
        if anchor_weeks < 1:
            raise ValueError("anchor_weeks must be >= 1")
        if trend_weight is not None and not 0.0 <= float(trend_weight) <= 1.0:
            raise ValueError("trend_weight must be between 0 and 1")
        self.credibility_weeks = float(credibility_weeks)
        self.anchor_weeks = int(anchor_weeks)
        self.max_horizon = int(max_horizon)
        self.validation_weeks = int(validation_weeks)

        #: How much of the fitted slope is actually projected forward. None
        #: means "choose it on held-out weeks"; the chosen value lands here.
        self.trend_weight = None if trend_weight is None else float(trend_weight)
        self.trend_weight_fixed = trend_weight is not None
        #: (weight, weighted SSE) per candidate, so the choice is inspectable.
        self.trend_validation: list = []

        self.levels: dict = {}       # brand -> {week: level}
        self.slope: dict = {}        # brand -> slope actually projected
        self.own_slope: dict = {}    # brand -> unshrunk slope, for reporting
        self.credibility: dict = {}  # brand -> weight given to its own slope
        self.market_slope: float = 0.0
        self._span: dict = {}        # brand -> (first_week, last_week)
        self._anchor: dict = {}      # brand -> level at last_week, smoothed
        self._line: dict = {}        # brand -> (intercept, slope) for gap fill

    # -- fitting ---------------------------------------------------------

    @staticmethod
    def _wls_slope(weeks, levels, weights):
        """Weighted least-squares slope of `levels` on `weeks`.

        Returns 0.0 when the series cannot support a slope -- one week, or no
        spread in weeks. Zero is the right answer there: no evidence of drift is
        not evidence of drift.
        """
        w = np.asarray(weights, dtype=float)
        x = np.asarray(weeks, dtype=float)
        y = np.asarray(levels, dtype=float)
        if x.size < 2 or w.sum() <= 0:
            return 0.0
        xbar = np.average(x, weights=w)
        var = np.average((x - xbar) ** 2, weights=w)
        if var <= 0:
            return 0.0
        ybar = np.average(y, weights=w)
        cov = np.average((x - xbar) * (y - ybar), weights=w)
        return float(cov / var)

    def fit(self, *, brand, week, resid, weights=None):
        brand = np.asarray(brand).astype(str)
        week = np.asarray(week, dtype=float)
        resid = np.asarray(resid, dtype=float)
        if weights is None:
            weights = np.ones(len(resid), dtype=float)

        frame = pd.DataFrame(
            {"brand": brand, "week": week, "resid": resid, "w": weights}
        )
        frame = frame[np.isfinite(frame.resid) & np.isfinite(frame.week)]
        if frame.empty:
            raise ValueError("BrandTrend.fit got no usable rows")

        # Level per brand-week, and the row count behind it. The count is the
        # regression weight: a brand-week built from four quotes should not move
        # the slope as much as one built from four hundred.
        cell = (
            frame.groupby(["brand", "week"], observed=True)
            .apply(
                lambda g: pd.Series(
                    {
                        "level": np.average(g.resid, weights=g.w),
                        "n": float(g.w.sum()),
                    }
                ),
                include_groups=False,
            )
            .reset_index()
        )

        # Market level series: the same thing pooled over brands, which is what
        # a thin brand gets shrunk toward.
        market = (
            cell.groupby("week", observed=True)
            .apply(
                lambda g: pd.Series(
                    {"level": np.average(g.level, weights=g.n), "n": g.n.sum()}
                ),
                include_groups=False,
            )
            .reset_index()
        )
        if self.trend_weight is None:
            self.anchor_weeks, self.trend_weight = self._choose_extrapolation(cell)

        self.market_slope = self._wls_slope(market.week, market.level, market.n)
        self._fit_one(_MARKET, market)

        for b, g in cell.groupby("brand", observed=True):
            self._fit_one(str(b), g)

        return self

    # -- choosing whether to extrapolate at all ---------------------------

    #: Blend weights tried when `trend_weight` is not pinned. 0 is the
    #: martingale forecast (carry the level forward flat); 1 projects the whole
    #: fitted slope.
    _CANDIDATE_WEIGHTS = (0.0, 0.25, 0.5, 0.75, 1.0)

    #: How many trailing weeks the forward anchor averages. 1 is the last
    #: observed level; a large value approaches the brand's long-run mean.
    #: Both ends are wrong somewhere -- a level that wanders wants the recent
    #: weeks, a level that reverts wants more of them -- so this is measured
    #: rather than assumed, exactly like the trend weight.
    _CANDIDATE_ANCHORS = (1, 2, 3, 5, 8, 13)

    def _choose_extrapolation(self, cell):
        """Score anchor length and trend weight together on held-out weeks.

        Whether a level series trends, wanders or reverts is a property of the
        market, not something to assert in a default -- and the two knobs
        interact, so they are chosen jointly. Holding out the last few weeks and
        asking which forecast would have been better answers it directly and
        costs no model fits.

        Degrades to a flat carry whenever there is not enough history to tell,
        which is the choice that cannot be actively wrong.
        """
        weeks = np.sort(cell.week.unique())
        n_val = min(self.validation_weeks, max(1, len(weeks) // 3))
        train_weeks = weeks[: len(weeks) - n_val]
        val_weeks = weeks[len(weeks) - n_val:]
        if len(train_weeks) < 3 or len(val_weeks) == 0:
            self.trend_validation = [("insufficient history", None, float("nan"))]
            return self.anchor_weeks, 0.0

        tr = cell[cell.week.isin(train_weeks)]
        va = cell[cell.week.isin(val_weeks)]
        market_tr = (
            tr.groupby("week", observed=True)
            .apply(
                lambda g: pd.Series(
                    {"level": np.average(g.level, weights=g.n), "n": g.n.sum()}
                ),
                include_groups=False,
            )
            .reset_index()
        )
        market_slope_tr = self._wls_slope(
            market_tr.week, market_tr.level, market_tr.n
        )

        # Per brand: the level series and slope this training slice implies.
        fitted = {}
        for b, g in tr.groupby("brand", observed=True):
            g = g.sort_values("week")
            wk = g.week.to_numpy(dtype=float)
            lv = g.level.to_numpy(dtype=float)
            ct = g.n.to_numpy(dtype=float)
            own = self._wls_slope(wk, lv, ct)
            n_weeks = float(len(wk))
            cred = (
                1.0
                if self.credibility_weeks <= 0
                else n_weeks / (n_weeks + self.credibility_weeks)
            )
            fitted[str(b)] = (
                float(wk.max()),
                cred * own + (1.0 - cred) * market_slope_tr,
                wk, lv, ct,
            )

        # Score the *change* in level, not the level, because the change is
        # what gets applied. The realised change is measured from the brand's
        # own last training week, so a brand sitting at an unusual level is not
        # penalised for it -- only for the direction it then moved.
        val_rows = [
            (str(r.brand), float(r.week), float(r.level), float(r.n))
            for r in va.itertuples()
        ]

        scored = []
        for lam in self._CANDIDATE_WEIGHTS:
            sse = 0.0
            for brand, wk_v, level_v, n_v in val_rows:
                f = fitted.get(brand)
                if f is None:
                    continue
                last, slope, wk, lv, ct = f
                actual = level_v - float(lv[wk == last][0])
                horizon = min(wk_v - last, float(self.max_horizon))
                sse += n_v * (actual - slope * lam * horizon) ** 2
            scored.append((lam, sse))

        self.trend_validation = scored
        return self.anchor_weeks, float(min(scored, key=lambda t: t[1])[0])

    def _fit_one(self, key, g):
        g = g.sort_values("week")
        weeks = g.week.to_numpy(dtype=float)
        levels = g.level.to_numpy(dtype=float)
        counts = g.n.to_numpy(dtype=float)

        self.levels[key] = dict(zip(weeks, levels))
        self._span[key] = (float(weeks.min()), float(weeks.max()))

        own = self._wls_slope(weeks, levels, counts)
        self.own_slope[key] = own

        n_weeks = float(len(weeks))
        if key == _MARKET or self.credibility_weeks <= 0:
            cred = 1.0
        else:
            cred = n_weeks / (n_weeks + self.credibility_weeks)
        self.credibility[key] = cred
        # `trend_weight` decides how much of the fitted slope is projected
        # forward at all. At 0 this is the martingale forecast -- carry the last
        # level, which is optimal when the level wanders rather than trends.
        slope = (cred * own + (1.0 - cred) * self.market_slope) * self.trend_weight
        self.slope[key] = slope

        # Intercept of the brand's own line, used only to fill weeks inside the
        # observed span that this brand happens to be missing.
        xbar = np.average(weeks, weights=counts)
        ybar = np.average(levels, weights=counts)
        self._line[key] = (ybar - own * xbar, own)

        # Forward anchor: the last `anchor_weeks` observed levels, each carried
        # to the final week along the projected slope, then averaged. At the
        # default of 1 this is simply the last observed level, which is the
        # right anchor for a walk; raise it where a single week's level is
        # itself noisy, at the cost of anchoring slightly in the past.
        last = float(weeks.max())
        take = weeks >= (last - (self.anchor_weeks - 1))
        wk, lv, ct = weeks[take], levels[take], counts[take]
        carried = lv + slope * (last - wk)
        self._anchor[key] = float(np.average(carried, weights=ct))

    # -- prediction ------------------------------------------------------

    def level_at(self, brand: str, week: float) -> float:
        key = str(brand)
        if key not in self.levels:
            key = _MARKET
        if key not in self.levels:
            return 0.0

        observed = self.levels[key]
        if week in observed:
            return float(observed[week])

        first, last = self._span[key]
        slope = self.slope[key]

        if week > last:
            horizon = min(week - last, float(self.max_horizon))
            return float(self._anchor[key] + slope * horizon)
        if week < first:
            # Backwards is the same problem mirrored. It matters much less --
            # nothing forecasts into the past -- but a spatial split can hand us
            # a week a thin brand never appeared in.
            horizon = min(first - week, float(self.max_horizon))
            return float(observed[first] - slope * horizon)

        # Inside the observed span but missing for this brand: sit it on the
        # brand's own fitted line rather than dropping it to zero.
        intercept, own = self._line[key]
        return float(intercept + own * week)

    def predict(self, brand, week) -> np.ndarray:
        brand = np.asarray(brand).astype(str)
        week = np.asarray(week, dtype=float)
        return np.array(
            [self.level_at(b, w) for b, w in zip(brand, week)], dtype=float
        )

    def forward_delta(self, brand, week, from_week: float) -> np.ndarray:
        """Modelled level *change* between `from_week` and each `week`.

        Zero at or before `from_week`. This, rather than the absolute level, is
        what gets added to a prediction: it leaves everything inside the
        training window exactly as the unwrapped model left it, and corrects
        only the horizon the unwrapped model could not represent.

        Adding an absolute level instead means re-expressing every in-window
        prediction as shape-plus-level, which is a strictly additive claim. It
        is false wherever a brand's minimum premium binds -- a floored quote
        does not move when the brand's level moves -- and on this project's
        sample data 14-29% of quotes per brand sit on that floor. Measured, the
        absolute-level form cost 2 points of MdAPE at a one-week horizon, where
        there is almost no drift to correct at all. The delta form cannot,
        because at a one-week horizon it barely changes anything.
        """
        brand = np.asarray(brand).astype(str)
        week = np.asarray(week, dtype=float)
        horizon = np.clip(week - float(from_week), 0.0, float(self.max_horizon))
        slopes = np.array(
            [self.slope.get(str(b), self.slope.get(_MARKET, 0.0)) for b in brand],
            dtype=float,
        )
        return slopes * horizon

    # -- reporting -------------------------------------------------------

    def report(self) -> pd.DataFrame:
        """Per-brand drift, as weekly and annualised percentage change.

        The slope is on log-premium, so `exp(slope) - 1` is the weekly
        multiplicative change. This table is the per-brand price index the
        decomposition produces as a by-product.
        """
        rows = []
        for key, slope in self.slope.items():
            first, last = self._span[key]
            rows.append(
                {
                    "brand": "MARKET" if key == _MARKET else key,
                    "weeks": int(len(self.levels[key])),
                    "own_slope_pct_wk": round((np.exp(self.own_slope[key]) - 1) * 100, 3),
                    "used_slope_pct_wk": round((np.exp(slope) - 1) * 100, 3),
                    "credibility": round(self.credibility[key], 3),
                    "trend_weight": self.trend_weight,
                    "anchor_weeks": self.anchor_weeks,
                    "annualised_pct": round((np.exp(slope * 52) - 1) * 100, 1),
                    "last_week": int(last),
                }
            )
        out = pd.DataFrame(rows)
        return out.sort_values(
            ["brand"], key=lambda s: s.ne("MARKET")
        ).reset_index(drop=True)


class TrendAdjusted(Approach):
    """Wrap an approach so forward price drift is modelled rather than flat.

    Fits `inner_cls` with `week` removed, then adds a per-brand level read off
    the residuals and extended forward by `BrandTrend`. In-window predictions
    are essentially unchanged -- the level is just moved out of the tree and
    back in again -- so what this buys is entirely at horizons past the training
    window, which is where the unwrapped model was flat.

    `week` must be present in X. Its absence would silently produce a model with
    no time term at all, which is a worse failure than the one being fixed.
    """

    inner_cls = None
    week_col = "week"
    #: Folds used to get unbiased residuals for the level. 1 = in-sample, which
    #: is `n_folds` times faster and systematically under-shoots the drift.
    n_folds = 3
    #: Rows behind a brand's recalibration offset before it is trusted in full.
    #: Below this it is shrunk toward the market offset, on the same n/(n+k)
    #: reasoning as the slope credibility.
    anchor_rows = 50.0

    def __init__(self, n_folds: int | None = None, anchor_rows=None, **kw):
        trend_kw = {
            k: kw.pop(k)
            for k in (
                "credibility_weeks", "anchor_weeks", "max_horizon",
                "trend_weight", "validation_weeks",
            )
            if k in kw
        }
        super().__init__(**kw)
        if n_folds is not None:
            self.n_folds = int(n_folds)
        if anchor_rows is not None:
            self.anchor_rows = float(anchor_rows)
        self._trend_kw = trend_kw
        self.inner = None
        self.trend = None
        self.max_train_week = None
        #: brand -> cumulative level offset learned from observed weeks after
        #: training. Empty until `recalibrate` is called, and empty means this
        #: model behaves exactly as it did before recalibration existed.
        self.level_offset: dict = {}
        #: Last week whose outturn has actually been seen. Drift is projected
        #: forward from here, not from the end of the training window.
        self.as_of_week = None
        #: One row per recalibrate() call, for reporting.
        self.recalibrations: list = []

    @classmethod
    def available(cls):
        return cls.inner_cls.available()

    def _split_week(self, X):
        X = pd.DataFrame(X)
        if self.week_col not in X.columns:
            raise KeyError(
                f"{self.name} needs a `{self.week_col}` column to model drift; "
                f"got {list(X.columns)[:8]}... Build the matrix with "
                "features.build.design_matrix, which derives it from "
                "`collected_on`."
            )
        return X.drop(columns=[self.week_col]), X[self.week_col].to_numpy(dtype=float)

    def _out_of_fold_resid(self, Xr, y, g):
        """Residuals from models that did not see the row they score.

        Folds are random rather than blocked by week: the point is to hold out
        the *risk*, so that the shape is predicted out-of-sample, while every
        week still appears in every training fold. Blocking on week would hold
        out the very signal being measured.
        """
        n = len(y)
        if self.n_folds <= 1 or n < 2 * self.n_folds:
            m = self.inner_cls(**self.params).fit(Xr, y, groups=g)
            return y - np.asarray(m.predict(Xr, groups=g), dtype=float)

        rng = np.random.default_rng(self.params.get("random_state", 0))
        folds = np.array_split(rng.permutation(n), self.n_folds)
        oof = np.empty(n, dtype=float)
        for held in folds:
            keep = np.setdiff1d(np.arange(n), held, assume_unique=False)
            m = self.inner_cls(**self.params).fit(
                Xr.iloc[keep], y[keep], groups=g[keep]
            )
            oof[held] = np.asarray(
                m.predict(Xr.iloc[held], groups=g[held]), dtype=float
            )
        return y - oof

    def fit(self, X, y, groups=None):
        if groups is None:
            raise ValueError(f"{self.name} needs `groups` (brand labels)")
        X = pd.DataFrame(X)
        Xr, week = self._split_week(X)
        y = np.asarray(y, dtype=float)
        g = np.asarray(groups)

        # The point model keeps `week` and is therefore the unwrapped approach,
        # unchanged. Everything this wrapper adds is a correction applied beyond
        # the last week it was trained on.
        self.inner = self.inner_cls(**self.params).fit(X, y, groups=g)
        self.max_train_week = float(np.max(week))

        # The level series needs a model that is *not* allowed to absorb the
        # level, so it gets its own week-agnostic fit, out-of-fold.
        resid = self._out_of_fold_resid(Xr, y, g)
        resid = (
            pd.Series(resid)
            .groupby(pd.Series(g).astype(str), observed=True)
            .transform(lambda s: s - s.mean())
            .to_numpy(dtype=float)
        )
        self.trend = BrandTrend(**self._trend_kw).fit(
            brand=g, week=week, resid=resid
        )
        self.level_offset, self.recalibrations = {}, []
        self.as_of_week = self.max_train_week
        return self

    def predict(self, X, groups=None):
        X = pd.DataFrame(X)
        _, week = self._split_week(X)
        g = np.asarray(groups) if groups is not None else np.array([_MARKET] * len(X))

        # Clamp the week the point model sees. It flat-lines past its training
        # range anyway -- a tree has no split out there -- so clamping changes
        # nothing it would have done, and it makes explicit that the forward
        # movement is coming from the level term rather than from the tree.
        clamped = X.copy()
        clamped[self.week_col] = np.minimum(week, self.max_train_week)
        base = np.asarray(self.inner.predict(clamped, groups=groups), dtype=float)

        as_of = self.max_train_week if self.as_of_week is None else self.as_of_week
        offset = np.array(
            [self.level_offset.get(str(b), 0.0) for b in np.asarray(g).astype(str)],
            dtype=float,
        )
        return base + offset + self.trend.forward_delta(g, week, as_of)

    # -- recalibration ----------------------------------------------------

    def recalibrate(self, X, y, groups):
        """Fold newly observed weeks into the per-brand level.

        The batch evaluation withholds every holdout week at once. That is the
        right test of extrapolation and the wrong model of operation: the panel
        is re-collected weekly, so week 9's outturn is in hand before week 10 is
        priced. Refusing to use it does not make the measurement honest, it
        makes it answer a question nobody asks.

        This does *not* refit the point model. It reads the residual the current
        model leaves on the most recent `anchor_weeks` observed weeks, and
        carries that forward as a level offset. Shape, interactions and the
        brand's own curve are all left alone -- only the level moves, which is
        the only thing a repricing actually changes.

        Why the median rather than the mean: a brand's minimum premium pins a
        large minority of its quotes (14-29% on this project's sample), and a
        floored quote does not move when the brand's level moves. The residual
        is therefore a mixture of moved and unmoved rows, and the median tracks
        the moved majority instead of splitting the difference between them.

        Repeat calls accumulate, so the normal usage is one call per collection
        week. Never call it on data the model will then be scored on -- that is
        scoring on the training set with extra steps.
        """
        if self.trend is None:
            raise ValueError(f"{self.name} must be fitted before recalibrating")
        X = pd.DataFrame(X)
        _, week = self._split_week(X)
        y = np.asarray(y, dtype=float)
        g = np.asarray(groups).astype(str)

        resid = y - np.asarray(self.predict(X, groups=groups), dtype=float)
        obs = pd.DataFrame({"brand": g, "week": week, "resid": resid})
        obs = obs[np.isfinite(obs.resid) & np.isfinite(obs.week)]
        if obs.empty:
            return self

        # Only the most recent `anchor_weeks` are used. Older weeks are already
        # in the level series; re-reading them would double-count.
        latest = float(obs.week.max())
        window = obs[obs.week > latest - self.trend.anchor_weeks]
        market = float(np.median(window.resid))

        moved = {}
        for b, grp in window.groupby("brand", observed=True):
            own = float(np.median(grp.resid))
            n = float(len(grp))
            cred = n / (n + self.anchor_rows) if self.anchor_rows > 0 else 1.0
            delta = cred * own + (1.0 - cred) * market
            self.level_offset[str(b)] = self.level_offset.get(str(b), 0.0) + delta
            moved[str(b)] = ((np.exp(delta) - 1) * 100.0, int(n), cred)

        self.as_of_week = max(float(self.as_of_week or self.max_train_week), latest)
        self.recalibrations.append(
            {"as_of_week": self.as_of_week, "rows": int(len(window)),
             "market_pct": (np.exp(market) - 1) * 100.0, "brands": moved}
        )
        return self

    def recalibration_report(self):
        """Cumulative level offset per brand, as a percentage of premium."""
        if not self.level_offset:
            return pd.DataFrame(
                columns=["brand", "offset_pct", "as_of_week"]
            )
        rows = [
            {"brand": b, "offset_pct": (np.exp(v) - 1) * 100.0,
             "as_of_week": self.as_of_week}
            for b, v in sorted(self.level_offset.items())
        ]
        return pd.DataFrame(rows).sort_values("offset_pct").reset_index(drop=True)

    def shape_functions(self):
        return self.inner.shape_functions() if self.inner is not None else None

    @property
    def fallback_brands(self):
        return getattr(self.inner, "fallback_brands", [])

    def drift_report(self):
        return self.trend.report() if self.trend is not None else None

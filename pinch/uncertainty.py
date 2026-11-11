"""Uncertainty of the energy targets caused by uncertain stream data (workflow steps 1-2).

Stream tables of a real plant come from rough estimates, design set points and a few measurements. This
module propagates their uncertainty to the targets and says which data matter, following

    Bergamini, Nguyen, Elmegaard (2019), "Simplification of Data Acquisition in Process Integration
    Retrofit Studies Based on Uncertainty and Sensitivity Analysis", Frontiers in Energy Research 7:108,
    DOI 10.3389/fenrg.2019.00108;
    Bergamini, Nguyen, Bellemo, Elmegaard (2021), Journal of Cleaner Production 284, 124634,
    DOI 10.1016/j.jclepro.2020.124634.

Method (Bergamini et al. 2019, Sec. 2.3.2-2.3.3; 2021, Sec. 3.3)
-----------------------------------------------------------------
1. Uncertainty of each input: heat loads relative, temperatures absolute. Default values are the
   "nominal uncertainty" of their Table 1 (heat flow 10 %, temperature 3 K), set for rough data
   estimates in a dairy plant: a starting point, not a property of any other plant.
2. N samples (default 5000, as theirs) by Latin hypercube sampling, propagated through the Problem
   Table Algorithm. Outputs: Qh,min, Qc,min, pinch T*.
3. Monte Carlo error of each mean, MCerr = σ_y / √N (2019, Eq. 1).
4. Standardised regression coefficients (SRC): a linear model of the mean-centred, σ-scaled output on the
   mean-centred, σ-scaled inputs (2021, Eq. 2). If R² > 0.7 the squared coefficients β² rank the
   inputs; an input with β² < 0.01 for every output contributes less than 1 % of each output's variance
   and needs no better measurement (2021, Sec. 3.3). For the pinch temperature the linear model is often
   poor (2019 found R² = 0.48), so its ranking is reported only when R² > 0.7.

Choices of this module (not from the sources)
---------------------------------------------
* Normal distributions (the sources give standard deviations). Heat loads are truncated at a small
  positive value.
* A stream whose temperature interval is at most ``latent_width_K`` (default 1 K, the convention for
  latent loads in the brewery case) moves as a whole: one temperature sample shifts both ends, because
  the uncertain quantity is the saturation temperature, not the 1 K width. Other streams get independent
  samples for each end; a sample that would reverse a stream's direction or leave it narrower than
  ``latent_width_K`` is replaced by the nominal width around the sampled mid-point.
* Temperature shifts ΔT_shift are not varied: they are design choices, not measurements.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd
from scipy.stats import norm, qmc

from pinch.problem_table_algorithm import problem_table
from pinch.streams import StreamSet

#: Bergamini et al. (2019), Table 1, "nominal uncertainty" of rough data estimates (dairy case).
BERGAMINI_2019_SIGMA = {"heat_flow_relative": 0.10, "temperature_K": 3.0}
#: SRC screening (Bergamini et al. 2021, Sec. 3.3): linear model acceptable above this R², input negligible below this β².
SRC_R2_MIN, SRC_BETA2_MIN = 0.7, 0.01


@dataclass(frozen=True)
class UncertaintyResult:
    samples: pd.DataFrame        # one row per sample: inputs and outputs
    summary: pd.DataFrame        # per output: nominal, mean, std, relative std, MCerr, 2.5 / 97.5 percentiles
    src: pd.DataFrame            # per input: beta² for each output (nan where R² <= 0.7)
    r2: dict[str, float]         # R² of the linear model for each output
    nominal: dict[str, float]

    def important_inputs(self) -> list[str]:
        """Inputs with β² >= 0.01 for at least one output whose linear model has R² > 0.7."""
        cols = [c for c in self.src.columns if self.r2.get(c, 0.0) > SRC_R2_MIN]
        if not cols:
            return []
        keep = (self.src[cols] >= SRC_BETA2_MIN).any(axis=1)
        return list(self.src.index[keep])


def _outputs(streams: StreamSet) -> tuple[float, float, float]:
    t = problem_table(streams)
    pinch = max(t.pinch_T_star_C) if t.pinch_T_star_C else np.nan
    return t.Qh_min, t.Qc_min, pinch


def _src(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    """Standardised regression coefficients and R² (Bergamini et al. 2021, Eq. 2)."""
    sx, sy = X.std(axis=0, ddof=1), y.std(ddof=1)
    ok = sx > 0
    beta = np.full(X.shape[1], np.nan)
    if sy == 0 or not ok.any():
        return beta, np.nan
    Z = (X[:, ok] - X[:, ok].mean(axis=0)) / sx[ok]
    zy = (y - y.mean()) / sy
    coef, *_ = np.linalg.lstsq(Z, zy, rcond=None)
    resid = zy - Z @ coef
    r2 = 1.0 - float(resid @ resid) / float(zy @ zy)
    beta[ok] = coef
    return beta, r2


def target_uncertainty(streams: StreamSet, *, heat_flow_relative: float | dict[str, float] = 0.10,
                       temperature_K: float | dict[str, float] = 3.0, n: int = 5000, seed: int = 0,
                       latent_width_K: float = 1.0) -> UncertaintyResult:
    """Monte Carlo propagation of stream-data uncertainty to Qh,min, Qc,min and the pinch.

    ``heat_flow_relative`` and ``temperature_K`` are one value for all streams or a dict by stream name
    (streams not in the dict take the defaults of Bergamini et al. 2019, Table 1). Deterministic for a seed.
    """
    if n < 10:
        raise ValueError("n must be >= 10")
    S = streams.streams
    sq = [heat_flow_relative.get(s.name, BERGAMINI_2019_SIGMA["heat_flow_relative"])
          if isinstance(heat_flow_relative, dict) else heat_flow_relative for s in S]
    st = [temperature_K.get(s.name, BERGAMINI_2019_SIGMA["temperature_K"])
          if isinstance(temperature_K, dict) else temperature_K for s in S]
    lumped = [abs(s.T_out_C - s.T_in_C) <= latent_width_K + 1e-12 for s in S]

    names: list[str] = []
    for s, lump in zip(S, lumped):
        names.append(f"{s.name}: Q")
        names += [f"{s.name}: T"] if lump else [f"{s.name}: T_in", f"{s.name}: T_out"]
    U = norm.ppf(qmc.LatinHypercube(d=len(names), seed=seed).random(n))   # standard normal, LHS

    X = np.empty((n, len(names)))
    rows = []
    for k in range(n):
        new, c = [], 0
        for s, lump, a, b in zip(S, lumped, sq, st):
            Q = max(s.Q * (1.0 + a * U[k, c]), 1e-9 * s.Q)
            X[k, c] = Q
            c += 1
            if lump:
                d = b * U[k, c]
                X[k, c] = s.T_in_C + d
                Ti, To = s.T_in_C + d, s.T_out_C + d
                c += 1
            else:
                Ti, To = s.T_in_C + b * U[k, c], s.T_out_C + b * U[k, c + 1]
                X[k, c], X[k, c + 1] = Ti, To
                c += 2
                wrong = (To >= Ti - latent_width_K) if s.kind == "hot" else (To <= Ti + latent_width_K)
                if wrong:
                    mid, half = (Ti + To) / 2, (s.T_out_C - s.T_in_C) / 2
                    Ti, To = mid - half, mid + half
            new.append(replace(s, Q=Q, T_in_C=Ti, T_out_C=To))
        rows.append(_outputs(replace(streams, streams=tuple(new))))

    out_names = ["Qh_min", "Qc_min", "pinch_T_star_C"]
    Y = np.array(rows)
    samples = pd.concat([pd.DataFrame(X, columns=names), pd.DataFrame(Y, columns=out_names)], axis=1)
    nominal = dict(zip(out_names, _outputs(streams)))
    summary = []
    for j, o in enumerate(out_names):
        y = Y[:, j][np.isfinite(Y[:, j])]
        sd = float(y.std(ddof=1))
        summary.append({"output": o, "nominal": nominal[o], "mean": float(y.mean()), "std": sd,
                        "relative_std": sd / abs(float(y.mean())) if y.mean() else np.nan,
                        "MCerr": sd / np.sqrt(len(y)), "p2.5": float(np.percentile(y, 2.5)),
                        "p97.5": float(np.percentile(y, 97.5))})
    src, r2 = {}, {}
    for j, o in enumerate(out_names):
        fin = np.isfinite(Y[:, j])
        beta, r = _src(X[fin], Y[fin, j])
        src[o], r2[o] = beta ** 2, r
    return UncertaintyResult(samples=samples, summary=pd.DataFrame(summary).set_index("output"),
                             src=pd.DataFrame(src, index=names), r2=r2, nominal=nominal)

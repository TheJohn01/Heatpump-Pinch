"""Data reconciliation of measured plant data before a pinch study (workflow step 1).

Measured temperatures and heat capacity flow rates (CP) of an existing heat exchanger network do not
close the exchangers' heat balances. Reconciliation adjusts them, each in proportion to its
uncertainty, until every balance closes. This module implements the method of

    Yong, Nemet, Varbanov, Kravanja, Klemeš (2016), "Data Reconciliation for Total Site Integration",
    Chemical Engineering Transactions 52, 1045-1050, DOI 10.3303/CET1652175,

which minimises the weighted squared adjustments of CP and T (their Eqs 1-2) subject to each
exchanger's energy balance CP_hot (T_hot,in - T_hot,out) = CP_cold (T_cold,out - T_cold,in) (Eq. 5).

Two solution methods
--------------------
* ``method="simultaneous"`` (default): all CPs and temperatures adjusted together. The bilinear balances
  are linearised around the current estimate and the linear problem is solved in closed form, repeated
  until the estimate stops changing (successive linearisation; standard practice, not taken from Yong et
  al.). This is the weighted least-squares solution of the full problem.
* ``method="iterative"``: the method of Yong et al. (2016, Fig. 1): CP model with T fixed at the
  measured values, then T model with the CPs just found, repeated (their steps 3-5). The authors state
  that it "features some inaccuracy, compared to the simultaneous method". Tests here show why: the
  first sub-model already closes every balance, so the second changes nothing and the whole correction
  falls on the CPs (or on the temperatures, if the T model goes first). Kept to reproduce the paper.

Their mass balances (Eqs 3-4: the CP of a stream is the same at inlet and outlet) hold by construction
here: each stream side has one CP variable. Streams that pass through several exchangers share the CP
variable and the temperature at each connection, which is how the network constraints enter.

Weights. Yong et al. write the weight as "the inverse of standard deviation of data measured", citing
Narasimhan and Jordache (2000). This module uses the inverse variance, w = 1/σ², the weighting for
which weighted least squares is the maximum-likelihood estimate under independent normal errors
(standard statistics). The two coincide when all σ are equal.

Each linear step has the closed-form solution of a linearly constrained weighted least-squares problem:

    x̂ = x - V Aᵀ (A V Aᵀ)⁻¹ (A x - b),   V = diag(σ²).

Gross errors. After reconciliation, S = sum ((x̂ - x) / σ)² is compared with the chi-square
distribution with as many degrees of freedom as independent balances (the global test of standard data
reconciliation practice). A value above the 95th percentile suggests a gross error (a faulty
instrument, a wrong flow assignment) rather than random noise. With the alternating method the test is
approximate. Not taken from Yong et al.; reported as an indicator only.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import chi2


@dataclass(frozen=True)
class Measurement:
    """A measured value and its standard deviation (same unit). σ = 0 fixes the value."""

    value: float
    sigma: float

    def __post_init__(self) -> None:
        if self.sigma < 0 or not np.isfinite(self.value) or not np.isfinite(self.sigma):
            raise ValueError("a measurement needs a finite value and sigma >= 0")


@dataclass(frozen=True)
class Exchanger:
    """One heat exchanger: names of the variables on each side.

    ``CP_*`` name heat capacity flow rates; ``T_*`` name temperatures [°C]. The same name in two
    exchangers means the same physical quantity (e.g. the outlet of one exchanger is the inlet of the
    next, or a stream keeps its CP through several exchangers).
    """

    name: str
    CP_hot: str
    T_hot_in: str
    T_hot_out: str
    CP_cold: str
    T_cold_in: str
    T_cold_out: str


def reconcile_linear(x, sigma, A, b=None) -> np.ndarray:
    """Weighted least-squares adjustment of ``x`` so that ``A x = b``.

    Parameters
    ----------
    x : measured values, shape (n,).
    sigma : standard deviations, shape (n,); 0 keeps a value fixed.
    A : constraint matrix, shape (m, n), rows linearly independent over the free variables.
    b : right-hand side, shape (m,); zeros if omitted.

    Returns the reconciled values x̂ = x - V Aᵀ (A V Aᵀ)⁻¹ (A x - b), V = diag(σ²).
    """
    x = np.asarray(x, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    A = np.atleast_2d(np.asarray(A, dtype=float))
    b = np.zeros(A.shape[0]) if b is None else np.asarray(b, dtype=float)
    if x.shape != sigma.shape or A.shape[1] != x.size or b.size != A.shape[0]:
        raise ValueError("inconsistent shapes of x, sigma, A, b")
    V = np.diag(sigma ** 2)
    M = A @ V @ A.T
    if np.linalg.matrix_rank(M) < M.shape[0]:
        raise ValueError("constraints cannot all be met by adjusting the variables with sigma > 0")
    return x - V @ A.T @ np.linalg.solve(M, A @ x - b)


@dataclass(frozen=True)
class ReconciliationResult:
    """Reconciled values, their adjustments and the global test."""

    values: dict[str, float]
    adjustments: dict[str, float]          # reconciled - measured
    normalised_adjustments: dict[str, float]  # (reconciled - measured) / sigma; nan for fixed values
    test_statistic: float                  # sum of squared normalised adjustments
    degrees_of_freedom: int
    critical_value_95: float
    iterations: int
    max_balance_residual: float            # largest |Q_hot - Q_cold| after reconciliation

    @property
    def gross_error_suspected(self) -> bool:
        return self.test_statistic > self.critical_value_95

    def duties(self, exchangers: list[Exchanger]) -> dict[str, float]:
        """Reconciled duty of each exchanger, from its hot side [CP unit x K]."""
        v = self.values
        return {e.name: v[e.CP_hot] * (v[e.T_hot_in] - v[e.T_hot_out]) for e in exchangers}


def _balance(e: Exchanger, v: dict[str, float]) -> float:
    return v[e.CP_hot] * (v[e.T_hot_in] - v[e.T_hot_out]) - v[e.CP_cold] * (v[e.T_cold_out] - v[e.T_cold_in])


def reconcile_network(measurements: dict[str, Measurement], exchangers: list[Exchanger],
                      method: str = "simultaneous", tol: float = 1e-10, max_iter: int = 200) -> ReconciliationResult:
    """Reconcile CPs and temperatures of a network (see the module docstring for the two methods).

    Every variable named in ``exchangers`` must have a measurement (use a large sigma for an unmeasured
    value with a rough estimate). Iterates until no value changes by more than ``tol`` x (1 + |value|).
    """
    if method not in ("simultaneous", "iterative"):
        raise ValueError("method must be 'simultaneous' or 'iterative'")
    if not exchangers:
        raise ValueError("no exchangers")
    cp_names = sorted({n for e in exchangers for n in (e.CP_hot, e.CP_cold)})
    t_names = sorted({n for e in exchangers for n in (e.T_hot_in, e.T_hot_out, e.T_cold_in, e.T_cold_out)})
    if set(cp_names) & set(t_names):
        raise ValueError("a name is used both as a CP and as a temperature")
    missing = [n for n in cp_names + t_names if n not in measurements]
    if missing:
        raise ValueError(f"no measurement for {missing}")

    v = {n: measurements[n].value for n in cp_names + t_names}
    x_cp = np.array([measurements[n].value for n in cp_names])
    s_cp = np.array([measurements[n].sigma for n in cp_names])
    x_t = np.array([measurements[n].value for n in t_names])
    s_t = np.array([measurements[n].sigma for n in t_names])
    ic = {n: i for i, n in enumerate(cp_names)}
    it = {n: i for i, n in enumerate(t_names)}

    names = cp_names + t_names
    x_m = np.array([measurements[n].value for n in names])
    s_m = np.array([measurements[n].sigma for n in names])
    col = {n: i for i, n in enumerate(names)}

    iterations = 0
    for _ in range(max_iter):
        iterations += 1
        old = dict(v)
        if method == "simultaneous":
            # linearise g(x) = 0 at the current estimate x_k: g(x_k) + J (x - x_k) = 0, i.e. J x = J x_k - g(x_k)
            J = np.zeros((len(exchangers), len(names)))
            g = np.zeros(len(exchangers))
            for r, e in enumerate(exchangers):
                dTh, dTc = v[e.T_hot_in] - v[e.T_hot_out], v[e.T_cold_out] - v[e.T_cold_in]
                J[r, col[e.CP_hot]] += dTh
                J[r, col[e.T_hot_in]] += v[e.CP_hot]
                J[r, col[e.T_hot_out]] -= v[e.CP_hot]
                J[r, col[e.CP_cold]] -= dTc
                J[r, col[e.T_cold_out]] -= v[e.CP_cold]
                J[r, col[e.T_cold_in]] += v[e.CP_cold]
                g[r] = _balance(e, v)
            x_k = np.array([v[n] for n in names])
            for n, val in zip(names, reconcile_linear(x_m, s_m, J, J @ x_k - g)):
                v[n] = float(val)
            if all(abs(v[n] - old[n]) <= tol * (1 + abs(old[n])) for n in v):
                break
            continue
        # CP model: temperatures fixed, balances linear in CP
        A = np.zeros((len(exchangers), len(cp_names)))
        for r, e in enumerate(exchangers):
            A[r, ic[e.CP_hot]] += v[e.T_hot_in] - v[e.T_hot_out]
            A[r, ic[e.CP_cold]] -= v[e.T_cold_out] - v[e.T_cold_in]
        for n, val in zip(cp_names, reconcile_linear(x_cp, s_cp, A)):
            v[n] = float(val)
        # T model: CPs fixed, balances linear in T
        A = np.zeros((len(exchangers), len(t_names)))
        for r, e in enumerate(exchangers):
            A[r, it[e.T_hot_in]] += v[e.CP_hot]
            A[r, it[e.T_hot_out]] -= v[e.CP_hot]
            A[r, it[e.T_cold_out]] -= v[e.CP_cold]
            A[r, it[e.T_cold_in]] += v[e.CP_cold]
        for n, val in zip(t_names, reconcile_linear(x_t, s_t, A)):
            v[n] = float(val)
        if all(abs(v[n] - old[n]) <= tol * (1 + abs(old[n])) for n in v):
            break
    else:
        raise RuntimeError(f"reconciliation did not converge in {max_iter} iterations")

    adj = {n: v[n] - measurements[n].value for n in v}
    norm = {n: (adj[n] / measurements[n].sigma if measurements[n].sigma > 0 else float("nan")) for n in v}
    S = float(sum(z ** 2 for z in norm.values() if np.isfinite(z)))
    dof = len(exchangers)
    return ReconciliationResult(values=v, adjustments=adj, normalised_adjustments=norm, test_statistic=S,
                                degrees_of_freedom=dof, critical_value_95=float(chi2.ppf(0.95, dof)),
                                iterations=iterations,
                                max_balance_residual=max(abs(_balance(e, v)) for e in exchangers))

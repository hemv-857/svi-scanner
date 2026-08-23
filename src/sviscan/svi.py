"""Raw SVI parameterization, slice fitting, and no-arbitrage checks.

w(k) = a + b * ( rho*(k - m) + sqrt((k - m)^2 + sigma^2) ),   k = log-moneyness

No-arb conditions enforced numerically:
  butterfly: g(k) >= 0 for all k in the fitted range (Gatheral-Jacquier)
  calendar:  w_T2(k) >= w_T1(k) for T2 > T1 at common k
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares

__all__ = ["butterfly_ok", "calendar_ok", "fit_slice", "g_function", "svi_w", "total_variance"]


def svi_w(k: np.ndarray | float, params: np.ndarray) -> np.ndarray:
    """Total implied variance at log-moneyness k for raw-SVI params (a,b,rho,m,sigma)."""
    a, b, rho, m, sigma = params
    x = np.asarray(k, dtype=float) - m
    return a + b * (rho * x + np.sqrt(x * x + sigma * sigma))


def total_variance(iv: float, T: float) -> float:
    return iv * iv * T


def fit_slice(
    ks: np.ndarray, ws: np.ndarray, weights: np.ndarray | None = None
) -> tuple[np.ndarray, float]:
    """Fit raw SVI to one expiry slice; returns (params, rmse).

    ponytail: unconstrained LSQ on transformed params + validity penalty;
    full quasi-explicit global search only if this ever underfits.
    """
    ks = np.asarray(ks, float)
    ws = np.asarray(ws, float)
    wgt = np.ones_like(ws) if weights is None else np.asarray(weights, float)

    def resid(p):
        _a, b, rho, _m, sigma = p
        pen = 0.0
        if not (0 <= abs(rho) < 1):
            pen += 1e6 * (abs(rho) - 0.99) ** 2
        if sigma <= 1e-8:
            pen += 1e6 * (1e-8 - sigma) ** 2
        if abs(b) < 1e-10:
            pen += 1e6
        return wgt * (svi_w(ks, p) - ws) + pen

    # heuristic init: ATM level -> a; slope -> b*rho; curvature -> b*sigma
    atm = ws[len(ws) // 2] if len(ws) % 2 else ws.mean()
    p0 = np.array([max(atm * 0.5, 1e-6), max(atm, 1e-4), -0.3, 0.0, 0.1])
    res = least_squares(resid, p0, method="trf", max_nfev=5000)
    rmse = float(np.sqrt(np.mean(wgt * (svi_w(ks, res.x) - ws) ** 2)))
    return res.x, rmse


def g_function(k: np.ndarray, params: np.ndarray) -> np.ndarray:
    """Gatheral-Jacquier g(k): density-related quantity; g < 0 <=> butterfly arb."""
    a, b, rho, m, sigma = params
    k = np.asarray(k, dtype=float)
    x = k - m
    root = np.sqrt(x * x + sigma * sigma)
    w = a + b * (rho * x + root) + 1e-300
    wk = b * (rho + x / root)                      # d w/dk
    wkk = b * sigma * sigma / (root**3)            # d2 w/dk2
    return (1 - k * wk / (2 * w)) ** 2 - (wk / 4) * (1 / w + k * k / (4 * w)) * wk + wkk / 2


def butterfly_ok(params: np.ndarray, k_range: tuple[float, float], n: int = 401) -> bool:
    ks = np.linspace(*k_range, n)
    g = g_function(ks, params)
    return bool(np.all(g >= -1e-12))


def calendar_ok(params_short: np.ndarray, params_long: np.ndarray,
                k_range: tuple[float, float], n: int = 201) -> bool:
    """Total variance must be non-decreasing in maturity at every fixed k."""
    ks = np.linspace(*k_range, n)
    return bool(np.all(svi_w(ks, params_long) >= svi_w(ks, params_short) - 1e-12))


def find_butterfly_violations(params: np.ndarray,
                              k_grid: np.ndarray) -> np.ndarray:
    """Return k values where g(k) < 0 (empty array = clean)."""
    return k_grid[g_function(k_grid, params) < 0]


def find_calendar_violations(params_short: np.ndarray, params_long: np.ndarray,
                             k_grid: np.ndarray) -> np.ndarray:
    diff = svi_w(k_grid, params_long) - svi_w(k_grid, params_short)
    return k_grid[diff < -1e-12]

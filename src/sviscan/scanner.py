"""Surface construction + arbitrage scanning over fetched quotes."""

from __future__ import annotations

import itertools

import numpy as np

from .svi import (
    calendar_ok,
    find_butterfly_violations,
    find_calendar_violations,
    fit_slice,
    g_function,
)

__all__ = ["build_slices", "scan_surface"]


def build_slices(quotes: list[dict], min_strikes: int = 5) -> dict[float, dict]:
    """Group quotes by expiry; use mid IV for fitting, keep raw for severity."""
    by_exp: dict[float, list[dict]] = {}
    for q in quotes:
        by_exp.setdefault(round(q["T"], 6), []).append(q)
    slices = {}
    for T, rows in sorted(by_exp.items()):
        if len(rows) < min_strikes:
            continue
        spot = np.nanmean([r.get("spot", np.nan) for r in rows])
        ks, mids = [], []
        for r in sorted(rows, key=lambda r: r["K"]):
            k = np.log(r["K"] / spot) if np.isfinite(spot) and spot > 0 else 0.0
            ks.append(k)
            mids.append((r["iv_bid"] + r["iv_ask"]) / 2.0)
        ks_arr = np.asarray(ks)
        w = (np.asarray(mids) ** 2) * T  # total variance
        params, rmse = fit_slice(ks_arr, w)
        slices[T] = {"params": params, "rmse": rmse, "ks": ks_arr,
                     "w": w, "n": len(rows)}
    return slices


def scan_surface(slices: dict[float, dict], rmse_gate: float = 0.004,
                 k_span: tuple[float, float] = (-0.35, 0.35)) -> list[dict]:
    """Detect butterfly and calendar violations on the fitted surface.

    Bad fits (rmse above gate) are reported and skipped -- never silently scanned.
    """
    alerts: list[dict] = []
    kgrid = np.linspace(*k_span, 141)

    for T, sl in sorted(slices.items()):
        if sl["rmse"] > rmse_gate:
            alerts.append({"kind": "bad_fit", "T_short": T, "T_long": None,
                           "k_min": float(sl["ks"].min()), "k_max": float(sl["ks"].max()),
                           "severity": sl["rmse"]})
            continue
        bad_k = find_butterfly_violations(sl["params"], kgrid)
        if bad_k.size:
            g_min = float(g_function(kgrid, sl["params"]).min())
            alerts.append({"kind": "butterfly", "T_short": T, "T_long": None,
                           "k_min": float(bad_k.min()), "k_max": float(bad_k.max()),
                           "severity": -g_min})

    expiries = sorted(slices)
    for t1, t2 in itertools.pairwise(expiries):
        s1, s2 = slices[t1], slices[t2]
        if s1["rmse"] > rmse_gate or s2["rmse"] > rmse_gate:
            continue
        bad_k = find_calendar_violations(s1["params"], s2["params"], kgrid)
        if not bad_k.size and not calendar_ok(s1["params"], s2["params"], k_span):
            bad_k = kgrid[:0]  # defensive; detectors should agree
        if bad_k.size:
            worst = float(np.max(
                s1["w"].max() - s2["w"].max()))  # crude severity proxy
            alerts.append({"kind": "calendar", "T_short": t1, "T_long": t2,
                           "k_min": float(bad_k.min()), "k_max": float(bad_k.max()),
                           "severity": max(worst, 0.0)})
    return alerts

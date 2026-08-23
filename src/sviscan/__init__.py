"""sviscan: SVI vol-surface fitting + live no-arbitrage scanner."""

from .scanner import build_slices, scan_surface
from .svi import (
    butterfly_ok,
    calendar_ok,
    fit_slice,
    g_function,
    svi_w,
    total_variance,
)

__version__ = "0.1.0"
__all__ = [
    "build_slices",
    "butterfly_ok",
    "calendar_ok",
    "fit_slice",
    "g_function",
    "scan_surface",
    "svi_w",
    "total_variance",
]

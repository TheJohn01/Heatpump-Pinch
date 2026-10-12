"""Figures for the pinch analysis, saved to file with labelled axes and units."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # file output only; deterministic, no display needed
import matplotlib.pyplot as plt

from pinch.curves import composite_curve, grand_composite_curve
from pinch.problem_table import ProblemTable
from pinch.streams import StreamSet

HOT_COLOUR = "#C0392B"
COLD_COLOUR = "#2471A3"
GCC_COLOUR = "#1F2A30"


def plot_composite_curves(
    stream_set: StreamSet, table: ProblemTable, path: str | Path, title: str = ""
) -> Path:
    """Plot the shifted hot and cold composite curves and save the figure.

    The cold composite is offset by Qc_min so that the curves touch at the
    pinch. Returns the output path.
    """
    H_hot, T_hot = composite_curve(stream_set, "hot", shifted=True)
    H_cold, T_cold = composite_curve(stream_set, "cold", shifted=True, H_offset=table.Qc_min)
    unit = table.energy_unit

    fig, ax = plt.subplots(figsize=(7, 4.8))
    ax.plot(H_hot, T_hot, color=HOT_COLOUR, lw=2, label="Hot composite")
    ax.plot(H_cold, T_cold, color=COLD_COLOUR, lw=2, label="Cold composite")
    for T in table.pinch_T_star_C:
        ax.axhline(T, color="grey", ls=":", lw=1)
        ax.annotate(f"Pinch T* = {T:g} °C", xy=(ax.get_xlim()[1], T), xytext=(-4, 4),
                    textcoords="offset points", ha="right", fontsize=8, color="grey")
    ax.set_xlabel(f"Enthalpy, H [{unit}]")
    ax.set_ylabel("Shifted temperature, T* [°C]")
    ax.set_title(title or "Shifted composite curves")
    ax.text(0.02, 0.97,
            f"$Q_{{h,min}}$ = {table.Qh_min:.2f} {unit}\n$Q_{{c,min}}$ = {table.Qc_min:.2f} {unit}",
            transform=ax.transAxes, va="top", fontsize=9)
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right")
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def plot_gcc(table: ProblemTable, path: str | Path, title: str = "") -> Path:
    """Plot the Grand Composite Curve and save the figure. Returns the output path."""
    H, T_star = grand_composite_curve(table)
    unit = table.energy_unit

    fig, ax = plt.subplots(figsize=(6, 4.8))
    ax.plot(H, T_star, color=GCC_COLOUR, lw=2, marker="o", ms=3)
    ax.axvline(0, color="grey", lw=0.8)
    for T in table.pinch_T_star_C:
        ax.axhline(T, color="grey", ls=":", lw=1)
        ax.annotate(f"Pinch T* = {T:g} °C", xy=(0, T), xytext=(4, 4),
                    textcoords="offset points", fontsize=8, color="grey")
    ax.set_xlabel(f"Net heat flow, H [{unit}]")
    ax.set_ylabel("Shifted temperature, T* [°C]")
    ax.set_title(title or "Grand Composite Curve")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path

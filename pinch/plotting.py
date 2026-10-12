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


def plot_gcc_with_units(table: ProblemTable, units, path: str | Path, title: str = "") -> Path:
    """GCC with heat pump sink and source profiles drawn as utility lines.

    Sinks are stacked from H = 0 in order of increasing temperature; sources
    likewise. Isothermal profiles are drawn as horizontal lines. Utility
    temperatures are plotted on the T* axis (dT_shift = 0 for utilities).
    """
    H, T_star = grand_composite_curve(table)
    unit_label = table.energy_unit
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(H, T_star, color=GCC_COLOUR, lw=2, label="GCC")

    H0 = 0.0
    for u in sorted(units, key=lambda u: u.T_sink_out_C):
        ax.plot([H0, H0 + u.Q_sink], [u.T_sink_in_C, u.T_sink_out_C], color=HOT_COLOUR, lw=2.5)
        ax.annotate(f"{u.name} sink ({u.Q_sink:.2f})", xy=(H0 + u.Q_sink, u.T_sink_out_C),
                    xytext=(-4, 5), textcoords="offset points", ha="right", fontsize=8, color=HOT_COLOUR)
        H0 += u.Q_sink

    H0 = 0.0
    sources = sorted([u for u in units if u.has_source], key=lambda u: u.T_source_out_C)
    for i, u in enumerate(sources):
        ax.plot([H0, H0 + u.Q_source], [u.T_source_in_C, u.T_source_out_C], color=COLD_COLOUR, lw=2.5)
        # Stagger labels so sources at the same temperature stay readable.
        ax.annotate(f"{u.name} source ({u.Q_source:.2f})", xy=(H0, u.T_source_out_C),
                    xytext=(2, -11 - 10 * i), textcoords="offset points", fontsize=8, color=COLD_COLOUR)
        H0 += u.Q_source

    for T in table.pinch_T_star_C:
        ax.axhline(T, color="grey", ls=":", lw=1)
    ax.axvline(0, color="grey", lw=0.8)
    ax.set_xlabel(f"Net heat flow, H [{unit_label}]")
    ax.set_ylabel("Shifted temperature, T* [°C]")
    ax.set_title(title or "GCC with heat pump placement")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path

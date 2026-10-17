"""Figures for the pinch analysis, with labelled axes and units.

The only module that draws with matplotlib (redundancy audit, item 5): every figure of the
dissertation, the analyses and the reproduction scripts is built here from tables the caller
computed. ``*_figure`` functions return a matplotlib Figure; ``save_figure`` writes one to file
and closes it. The app draws the same tables with Altair (``pinch.charts``).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display needed; deterministic output
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from pinch.curves import composite_curve
from pinch.problem_table_algorithm import ProblemTable
from pinch.streams import StreamSet

HOT_COLOUR = "#C0392B"
COLD_COLOUR = "#2471A3"
GCC_COLOUR = "#1F2A30"


def close_figure(fig: Figure) -> None:
    """Release a figure's memory (after it has been shown or saved)."""
    plt.close(fig)


def save_figure(fig: Figure, path: str | Path, dpi: int = 200) -> Path:
    """Save a figure (creating the folder) and close it. Returns the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return path


def composite_curves_figure(stream_set: StreamSet, table: ProblemTable, title: str = "") -> Figure:
    """Shifted hot and cold composite curves.

    The cold composite is offset by Qc_min so that the curves touch at the pinch.
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
    return fig


def gcc_figure(table: ProblemTable, title: str = "") -> Figure:
    """Grand Composite Curve."""
    H, T_star = table.cascade_feasible, table.T_star_C
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
    return fig


def gcc_with_units_figure(table: ProblemTable, units, title: str = "") -> Figure:
    """GCC with heat pump sink and source profiles drawn as utility lines.

    Sinks are stacked from H = 0 in order of increasing temperature; sources
    likewise. Isothermal profiles are drawn as horizontal lines. Utility
    temperatures are plotted on the T* axis (dT_shift = 0 for utilities).
    """
    H, T_star = table.cascade_feasible, table.T_star_C
    unit_label = table.energy_unit
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(H, T_star, color=GCC_COLOUR, lw=2, label="GCC")

    H0 = 0.0
    H_span = max(float(max(H)), sum(u.Q_sink for u in units), 1e-12)
    for u in sorted(units, key=lambda u: u.T_sink_out_C):
        ax.plot([H0, H0 + u.Q_sink], [u.T_sink_in_C, u.T_sink_out_C], color=HOT_COLOUR, lw=2.5)
        # Labels on short lines near the axis would run off the plot: anchor them left.
        near_axis = H0 + u.Q_sink < 0.4 * H_span
        ax.annotate(f"{u.name} sink ({u.Q_sink:.2f})", xy=(H0 + u.Q_sink, u.T_sink_out_C),
                    xytext=(4 if near_axis else -4, 5), textcoords="offset points",
                    ha="left" if near_axis else "right", fontsize=8, color=HOT_COLOUR)
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
    return fig


# ------------------------------------------------------------------ step 3
def supertargeting_figure(frames: list[pd.DataFrame], results: list[dict], title: str) -> Figure:
    """Total annual cost against ΔTmin, one line per cost law, optimum marked."""
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for df, r in zip(frames, results):
        ax.plot(df["dTmin_K"], df["TAC_EUR"] / 1e3, lw=1.8, label=f"b = {r['b']:.0f} EUR/m² (opt. {r['dTmin_opt_K']:g} K)")
        ax.plot(r["dTmin_opt_K"], r["TAC_min_EUR"] / 1e3, "o", color=ax.lines[-1].get_color())
    ax.set_xlabel("ΔTmin [K]")
    ax.set_ylabel("Total annual cost [k EUR/year]")
    ax.set_title(title)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7)
    fig.tight_layout()
    return fig


# ------------------------------------------------------------------ step 4
def config1_vs_fig11_figure(sweep: pd.DataFrame, config1: dict, T_gcc_max_C: float) -> Figure:
    """Padullés et al. (2026) configuration 1: our electricity against the points read from their Fig. 11."""
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    for label, colour, name in (("with_HR", "#2E7D32", "With heat recovery"), ("no_HR", "#2471A3", "No heat recovery")):
        ax.plot(sweep["T_steam_C"], sweep[f"W_{label}_kWh_hl"], color=colour, lw=2, label=f"{name} (this work)")
        pts = config1[f"W_figure_{label}"]["points"]
        ax.errorbar([float(t) for t in pts], list(pts.values()), yerr=config1[f"W_figure_{label}"]["uncertainty"],
                    fmt="o", color=colour, mfc="white", capsize=3, label=f"{name} (read from Fig. 11)")
    ax.axvline(T_gcc_max_C, color="grey", ls=":", lw=1)
    ax.annotate("GCC maximum T* = 103 °C", xy=(T_gcc_max_C, 1), xytext=(4, 0),
                textcoords="offset points", fontsize=8, color="grey")
    ax.set_xlabel("Utility steam temperature [°C]")
    ax.set_ylabel("Electricity consumption [kWh/hl]")
    ax.set_ylim(0, 25)
    ax.set_title("Configuration 1 (CCHS): this work vs. Padullés et al. (2026)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    return fig


# ------------------------------------------------------------------ step 5
def retrofit_options_figure(table: pd.DataFrame, title: str) -> Figure:
    """Gas reduction and payback of each retrofit option against the existing site."""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.5))
    y = np.arange(len(table))
    a1.barh(y, table["gas_reduction_vs_baseline"] * 100, color="#2471A3")
    a1.set_yticks(y, table["option"], fontsize=8)
    a1.set_xlabel("Gas reduction vs existing site [%]")
    a1.invert_yaxis()
    a1.grid(axis="x", alpha=0.3)
    pbp = table["payback_years"].replace([np.inf], np.nan)
    a2.barh(y, pbp, color="#C0392B")
    a2.set_yticks(y, [""] * len(y))
    a2.set_xlabel("Simple payback [years]")
    a2.set_xlim(0, 1.35 * float(np.nanmax(pbp)) if np.isfinite(np.nanmax(pbp)) else 10)
    a2.invert_yaxis()
    a2.grid(axis="x", alpha=0.3)
    for i, (p, npv) in enumerate(zip(pbp, table["npv_EUR"])):
        if np.isfinite(p):
            a2.annotate(f"NPV {npv / 1e6:+.2f} M€", (p, i), xytext=(3, 0), textcoords="offset points",
                        va="center", fontsize=7)
    fig.suptitle(title)
    fig.tight_layout()
    return fig


# ------------------------------------------------------------------ step 6
def electrification_curve_figure(curve_df: pd.DataFrame, threshold_years: float, horizon_years: int,
                                 discount_rate: float, title: str) -> Figure:
    """Payback and NPV along the electrification curve (share of Q̇h,min supplied by heat pumps)."""
    f = curve_df["fraction_of_Qh_min"] * 100
    fig, ax1 = plt.subplots(figsize=(7, 4.5))
    pbp = curve_df["payback_years"].replace(np.inf, np.nan)
    ax1.plot(f, pbp, color="#1F77B4", lw=2, label="Payback")
    ax1.axhline(threshold_years, color="#1F77B4", ls=":", lw=1)
    ax1.set_xlabel("Share of Q̇h,min supplied by heat pumps [%]")
    ax1.set_ylabel("Simple payback [years]", color="#1F77B4")
    ax1.set_ylim(0, max(3 * threshold_years, 1))
    ax2 = ax1.twinx()
    ax2.plot(f, curve_df["npv_EUR"] / 1e6, color="#D62728", lw=2, label=f"NPV{horizon_years}")
    ax2.axhline(0, color="#D62728", ls=":", lw=1)
    ax2.set_ylabel(f"NPV{horizon_years} at {100 * discount_rate:.0f} % [M EUR]", color="#D62728")
    ax1.set_title(title)
    ax1.grid(alpha=0.3)
    fig.tight_layout()
    return fig


def price_ratio_figure(sweep: pd.DataFrame, threshold_years: float, horizon_years: int, ratio: float,
                       title: str) -> Figure:
    """Payback and NPV of the full design against the electricity-to-gas price ratio."""
    fig, ax1 = plt.subplots(figsize=(7, 4.5))
    ax1.plot(sweep["ratio"], sweep["payback_years"].replace(np.inf, np.nan), color="#1F77B4", lw=2)
    ax1.axhline(threshold_years, color="#1F77B4", ls=":", lw=1)
    ax1.set_ylim(0, max(3 * threshold_years, 1))
    ax1.set_xlabel("Electricity-to-gas price ratio [-]")
    ax1.set_ylabel("Simple payback [years]", color="#1F77B4")
    ax2 = ax1.twinx()
    ax2.plot(sweep["ratio"], sweep["npv_EUR"] / 1e6, color="#D62728", lw=2)
    ax2.axhline(0, color="#D62728", ls=":", lw=1)
    ax2.set_ylabel(f"NPV{horizon_years} [M EUR]", color="#D62728")
    ax1.axvline(ratio, color="grey", ls="--", lw=1)
    ax1.annotate(f"case ratio {ratio:.2f}", xy=(ratio, 0.5), xytext=(4, 0),
                 textcoords="offset points", fontsize=8, color="grey")
    ax1.set_title(title)
    ax1.grid(alpha=0.3)
    fig.tight_layout()
    return fig


OPTION_MAP_COLOURS = ["#E6E6E6", "#1F77B4", "#2CA02C", "#FF7F0E", "#9467BD"]


def option_maps_figure(sizes_hl: np.ndarray, ratios: np.ndarray, maps: dict, names: list[str]) -> Figure:
    """Our version of Padullés et al. (2026), Figs. 18-19: optimal option by brewery size and price ratio.

    ``maps[(criterion, hr_installed)] = (grid, metric)``: option index (-1 = not viable) and the isoline
    quantity (payback [years] for "pbp", NPV10 [M EUR] for "npv") on the ratio x size grid.
    """
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), sharex=True, sharey=True)
    for col, criterion in enumerate(("pbp", "npv")):
        for row, hr in enumerate((False, True)):
            ax = axes[row, col]
            grid, metric = maps[(criterion, hr)]
            cmap = ListedColormap(OPTION_MAP_COLOURS)
            ax.pcolormesh(sizes_hl / 1e6, ratios, grid, cmap=cmap, vmin=-1.5, vmax=3.5, shading="auto")
            levels = (2, 3, 4, 6, 8) if criterion == "pbp" else (-2, 0, 2, 5, 10)
            cs = ax.contour(sizes_hl / 1e6, ratios, np.clip(metric, -50, 50), levels=levels, colors="k", linewidths=0.7)
            ax.clabel(cs, fmt="%g", fontsize=7)
            ax.set_title(f"{'PBP' if criterion == 'pbp' else 'NPV10'}-optimal, "
                         f"{'heat recovery installed' if hr else 'no heat recovery (tank included)'}", fontsize=9)
            if row == 1:
                ax.set_xlabel("Brewery size [million hl/year]")
            if col == 0:
                ax.set_ylabel("Electricity-to-gas price ratio [-]")
    handles = [Patch(color=c, label=l) for c, l in
               zip(OPTION_MAP_COLOURS, ["not viable (PBP > 4 y / NPV10 < 0)"] + names)]
    fig.legend(handles=handles, loc="lower center", ncol=5, fontsize=8)
    fig.suptitle("Optimal electrification option (this work; compare Padullés et al. 2026, Figs. 18-19). "
                 "Isolines: PBP [years] / NPV10 [M EUR]", fontsize=10)
    fig.tight_layout(rect=(0, 0.05, 1, 0.96))
    return fig


# ------------------------------------------------------------------ RQ1-RQ3
def tornado_figure(df: pd.DataFrame, col: str, title: str, xlabel: str) -> Figure:
    """One-at-a-time sensitivity of ``col``: first row is the base case; 'price_ratio' marks today's ratio."""
    base = df.iloc[0]
    d = df.iloc[1:].copy()
    d["delta"] = d[col] - base[col]
    d = d.reindex(d["delta"].abs().sort_values().index)
    fig, ax = plt.subplots(figsize=(9, 7))
    ax.barh(d["sensitivity"], d["delta"], left=base[col], color=["#2471A3" if v > 0 else "#C0392B" for v in d["delta"]])
    ax.axvline(base[col], color="black", lw=1)
    ax.axvline(base["price_ratio"], color="grey", ls="--", lw=1)
    ax.annotate(f"today's ratio {base['price_ratio']:.2f}", (base["price_ratio"], 0), xytext=(3, -12),
                textcoords="offset points", fontsize=7, color="grey")
    ax.set_xlabel(xlabel)
    ax.tick_params(axis="y", labelsize=7)
    ax.set_title(title, fontsize=10)
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    return fig


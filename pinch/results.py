"""Container for in-memory results, so that the same computation serves the
command line (written to files) and interactive front ends (shown on screen)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from matplotlib.figure import Figure

from pinch.plotting import close_figure, save_figure


@dataclass
class Outputs:
    """Results of one analysis block.

    Attributes
    ----------
    summary : dict
        JSON-serialisable key results.
    tables : dict
        File stem -> DataFrame (written as <stem>.csv).
    figures : dict
        File stem -> matplotlib Figure (written as <stem>.png).
    pngs : dict
        File stem -> PNG bytes, filled by ``snapshot_pngs`` (kept after ``write`` releases the figures,
        for the TEA report of ``pinch.report``).
    """

    summary: dict
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    figures: dict[str, Figure] = field(default_factory=dict)
    pngs: dict[str, bytes] = field(default_factory=dict)

    def snapshot_pngs(self, dpi: int = 200) -> dict[str, bytes]:
        """Render every open figure to PNG bytes (once per stem) and return all snapshots."""
        import io
        for stem, fig in self.figures.items():
            if stem not in self.pngs:
                buf = io.BytesIO()
                fig.savefig(buf, format="png", dpi=dpi)
                self.pngs[stem] = buf.getvalue()
        return self.pngs

    def write(self, out: str | Path, json_name: str | None = None) -> None:
        """Write tables (CSV), figures (PNG, then closed) and optionally the summary (JSON)."""
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        for stem, df in self.tables.items():
            df.to_csv(out / f"{stem}.csv", index=False)
        for stem, fig in self.figures.items():
            save_figure(fig, out / f"{stem}.png")
        self.figures = {}
        if json_name:
            (out / json_name).write_text(json.dumps(self.summary, indent=2, ensure_ascii=False, default=str),
                                         encoding="utf-8")

    def close_figures(self) -> None:
        """Release figure memory (call after displaying them)."""
        for fig in self.figures.values():
            close_figure(fig)
        self.figures = {}

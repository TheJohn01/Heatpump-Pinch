"""Colour palettes of the front end (light and dark) and the WCAG contrast check.

One source of truth for colour: ``.streamlit/config.toml`` repeats these values
because Streamlit reads its theme from that file, and
``tests/test_theme.py`` fails if the two drift apart.

Colour semantics (the same in both modes):

* ``hot`` (red) and ``cold`` (blue) are reserved for physics: hot streams,
  heating duty Q̇h and heat pump sinks; cold streams, cooling duty Q̇c and heat
  pump sources. They are never used for economics or for good/bad.
* ``accent`` (teal) is the interface colour (widgets, links) and the first
  colour of non-thermal charts; ``accent2`` (amber) is the second.
* ``ink`` is the text colour and the Grand Composite Curve; ``grey`` is for
  reference lines (pinch, thresholds).

Contrast follows WCAG 2.2 (W3C, 2023): text at least 4.5:1 against its
background (success criterion 1.4.3) and graphical objects, such as chart lines
and widget outlines, at least 3:1 (criterion 1.4.11).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Mode = Literal["light", "dark"]

TEXT_MIN_CONTRAST = 4.5
GRAPHIC_MIN_CONTRAST = 3.0


@dataclass(frozen=True)
class Palette:
    """Colours of one theme mode, as ``#RRGGBB`` strings."""

    mode: Mode
    background: str
    secondary_background: str
    text: str
    border: str
    primary: str  # widget fill (buttons, slider); white text sits on it
    link: str
    hot: str
    cold: str
    ink: str
    grey: str
    accent: str
    accent2: str

    seq_low: str  # light end of the sequential (teal) scale in this mode's sense
    seq_high: str
    div_mid: str  # neutral middle of the cold-to-hot diverging scale

    def categorical(self) -> list[str]:
        """Order of ``chartCategoricalColors``: physics first, then the neutral series."""
        return [self.hot, self.cold, self.ink, self.accent, self.accent2, self.grey]

    def sequential(self) -> list[str]:
        """Ten colours from ``seq_low`` to ``seq_high`` (``chartSequentialColors``)."""
        return ramp(self.seq_low, self.seq_high, 10)

    def diverging(self) -> list[str]:
        """Ten colours from cold through ``div_mid`` to hot (``chartDivergingColors``)."""
        return ramp(self.cold, self.div_mid, 6)[:5] + ramp(self.div_mid, self.hot, 6)[1:]


LIGHT = Palette(mode="light", background="#FFFFFF", secondary_background="#F3F5F6", text="#1F2A30",
                border="#D5DADD", primary="#0B7473", link="#0B7473", hot="#C0392B", cold="#2471A3",
                ink="#1F2A30", grey="#7F8C8D", accent="#0B7473", accent2="#B9770E",
                seq_low="#E3F2F1", seq_high="#0A4F4E", div_mid="#ECEFF1")

DARK = Palette(mode="dark", background="#11171A", secondary_background="#1B2327", text="#E4E9EB",
               border="#33404A", primary="#088E82", link="#4DB6AC", hot="#EE6C5B", cold="#5FA8E0",
               ink="#E4E9EB", grey="#8E9BA1", accent="#4DB6AC", accent2="#E3A33E",
               seq_low="#16403D", seq_high="#B5E4DF", div_mid="#2E393E")

PALETTES: dict[str, Palette] = {"light": LIGHT, "dark": DARK}


def palette_for(mode: str | None) -> Palette:
    """Palette for a theme type as reported by ``st.context.theme.type``; light when unknown."""
    return PALETTES.get(mode or "light", LIGHT)


def ramp(start: str, end: str, n: int) -> list[str]:
    """``n`` colours evenly interpolated in sRGB from ``start`` to ``end``, both included."""
    if n < 2:
        raise ValueError("a ramp needs at least two colours")
    a = [int(start.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(end.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return ["#" + "".join(f"{round(x + (y - x) * k / (n - 1)):02X}" for x, y in zip(a, b)) for k in range(n)]


def relative_luminance(hex_colour: str) -> float:
    """Relative luminance of an sRGB colour (WCAG 2.2 definition), between 0 and 1."""
    h = hex_colour.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"expected #RRGGBB, got {hex_colour!r}")
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio between two colours, from 1 (identical) to 21 (black on white)."""
    la, lb = sorted((relative_luminance(a), relative_luminance(b)))
    return (lb + 0.05) / (la + 0.05)

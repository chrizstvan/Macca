"""Centralised palette + Plotly defaults for the Macca dashboard.

Dark forest background, sage-green accent, warm earth-tone categorical
palette. Imported by ``app.py`` and every page so charts stay consistent.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

# --------------------------------------------------------------------------- #
# Palette                                                                      #
# --------------------------------------------------------------------------- #

BACKGROUND = "#0F1A12"          # deep forest
SURFACE = "#1C2B1F"             # cards / panels
SURFACE_ELEVATED = "#26382A"    # hovered / elevated surface
TEXT_PRIMARY = "#E8E1CC"        # warm ivory
TEXT_MUTED = "#9DB39C"          # sage-grey for captions
BORDER = "#2C3E2F"

PRIMARY = "#8AA77F"             # sage — main accent (buttons, sliders)
PRIMARY_STRONG = "#A8C698"      # hover / strong accent

ACCENT_LEAF = "#7FB069"          # vibrant leaf
ACCENT_MOSS = "#5D8A66"          # moss
ACCENT_PINE = "#3F5E48"          # deep pine
ACCENT_CLAY = "#C99B5B"          # warm clay
ACCENT_TERRA = "#A37B5C"         # terracotta
ACCENT_SAND = "#D9C58A"          # sand / cream

# Categorical sequence — used as ``color_discrete_sequence`` everywhere.
CATEGORICAL = (
    ACCENT_LEAF,
    ACCENT_CLAY,
    ACCENT_MOSS,
    ACCENT_TERRA,
    ACCENT_PINE,
    ACCENT_SAND,
)

# Status semantics.
STATUS_OK = ACCENT_LEAF          # 🟢 reported
STATUS_WARN = ACCENT_CLAY        # ⚠️ flagged / overdue
STATUS_BAD = "#C2553D"           # 🔴 not reported / failed


# --------------------------------------------------------------------------- #
# Plotly template                                                              #
# --------------------------------------------------------------------------- #


def install_plotly_theme() -> None:
    """Register a custom Plotly template and make it the default.

    Idempotent — safe to call from every page; later imports inherit the
    same defaults.
    """
    template = go.layout.Template(
        layout=go.Layout(
            colorway=list(CATEGORICAL),
            paper_bgcolor=SURFACE,
            plot_bgcolor=SURFACE,
            font=dict(color=TEXT_PRIMARY, family="Inter, system-ui, sans-serif"),
            title=dict(font=dict(color=TEXT_PRIMARY, size=16)),
            xaxis=dict(
                gridcolor=BORDER,
                zerolinecolor=BORDER,
                tickfont=dict(color=TEXT_MUTED),
                title=dict(font=dict(color=TEXT_MUTED)),
            ),
            yaxis=dict(
                gridcolor=BORDER,
                zerolinecolor=BORDER,
                tickfont=dict(color=TEXT_MUTED),
                title=dict(font=dict(color=TEXT_MUTED)),
            ),
            legend=dict(font=dict(color=TEXT_PRIMARY)),
            margin=dict(l=10, r=10, t=40, b=10),
        )
    )
    pio.templates["macca_earth"] = template
    pio.templates.default = "macca_earth"


# Auto-install on first import so pages don't need to remember to call it.
install_plotly_theme()

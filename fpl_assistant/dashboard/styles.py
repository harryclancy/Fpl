"""Shared visual styling: official Premier League brand colors, a hero
header, and small CSS tweaks layered on top of the dark theme set in
.streamlit/config.toml.

Colors are the Premier League's own published palette (Valentino purple,
Razzmatazz pink, and the two FPL accent tones), not an approximation —
consistency here is what makes the app read as "official" rather than a
generic dark theme.
"""
import pandas as pd
import streamlit as st

PURPLE = "#38003c"
PINK = "#e90052"
GREEN = "#00ff85"
CYAN = "#04f5ff"

GLOBAL_CSS = f"""
<style>
/* Metric cards */
div[data-testid="stMetric"] {{
    background: linear-gradient(145deg, #171729, #1d1d36);
    border: 1px solid rgba(255,255,255,0.08);
    border-left: 3px solid {GREEN};
    border-radius: 12px;
    padding: 14px 16px 10px 16px;
}}
div[data-testid="stMetricLabel"] {{ opacity: 0.75; }}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {{
    gap: 4px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
}}
.stTabs [data-baseweb="tab"] {{
    padding: 8px 16px;
    border-radius: 8px 8px 0 0;
}}
.stTabs [aria-selected="true"] {{
    background: linear-gradient(90deg, rgba(4,245,255,0.10), rgba(233,0,82,0.10));
}}
.stTabs [data-baseweb="tab-highlight"] {{
    background-color: {GREEN} !important;
}}

/* Dataframes / tables */
div[data-testid="stDataFrame"] {{
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid rgba(255,255,255,0.08);
}}

/* Section headers get a little breathing room */
h2, h3, h4 {{ margin-top: 0.4em; }}

/* Section banner (see section_header()) */
.section-banner {{
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin: 4px 0 14px 0;
    padding-bottom: 8px;
    border-bottom: 2px solid transparent;
    border-image: linear-gradient(90deg, {CYAN}, {PINK}) 1;
}}
.section-banner .title {{
    font-size: 20px;
    font-weight: 800;
    color: #ffffff;
}}
.section-banner .subtitle {{
    font-size: 12.5px;
    color: #9a9ab0;
}}

/* Hide the default Streamlit chrome that adds noise on mobile */
#MainMenu {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
</style>
"""

HERO_HTML = f"""
<div style="
    background: linear-gradient(120deg, {PURPLE} 0%, #1d1d36 60%, #0e0e1a 100%);
    border-radius: 16px;
    padding: 22px 26px 20px 26px;
    margin-bottom: 18px;
    border: 1px solid rgba(4,245,255,0.25);
    position: relative;
    overflow: hidden;
">
  <div style="position:absolute; top:0; left:0; right:0; height:4px;
              background: linear-gradient(90deg, {CYAN}, {GREEN}, {PINK});"></div>
  <div style="font-size: 28px; font-weight: 800; color: #ffffff; display:flex; align-items:center; gap:10px;">
    <span>⚽</span><span>FPL Assistant Manager</span>
  </div>
  <div style="font-size: 13.5px; color: #b9b9c9; margin-top: 4px;">
    Fixtures · Form · Captaincy · Injuries · Odds &amp; Expert Take — one view per gameweek
  </div>
</div>
"""


def inject_global_css() -> None:
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def hero_header() -> None:
    st.markdown(HERO_HTML, unsafe_allow_html=True)


def section_header(title: str, subtitle: str = "") -> None:
    subtitle_html = f'<span class="subtitle">{subtitle}</span>' if subtitle else ""
    st.markdown(
        f'<div class="section-banner"><span class="title">{title}</span>{subtitle_html}</div>',
        unsafe_allow_html=True,
    )


_FDR_STOPS = [(1, (0, 200, 90)), (3, (230, 200, 40)), (5, (220, 60, 60))]  # green -> amber -> red


def fdr_color(value: float) -> str:
    """Background color for a fixture-difficulty value (1=easiest..5=hardest),
    interpolated across a green -> amber -> red scale. No matplotlib
    dependency needed for one small gradient.
    """
    if pd.isna(value):
        return ""
    value = min(max(value, 1), 5)
    lo, hi = (_FDR_STOPS[0], _FDR_STOPS[1]) if value <= 3 else (_FDR_STOPS[1], _FDR_STOPS[2])
    span = hi[0] - lo[0]
    t = 0.0 if span == 0 else (value - lo[0]) / span
    rgb = tuple(round(lo[1][i] + t * (hi[1][i] - lo[1][i])) for i in range(3))
    return f"background-color: rgba({rgb[0]},{rgb[1]},{rgb[2]},0.55); color: #0e0e1a; font-weight: 700;"

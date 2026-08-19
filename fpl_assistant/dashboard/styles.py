"""Shared visual styling: typography, the Premier League brand palette,
a hero header, and the component CSS layered over the dark base theme in
.streamlit/config.toml.

Two things carry most of the visual weight here. Type: a condensed
display face for headings against a neutral UI face for everything else,
which is the pairing sports broadcasters use because it reads as
editorial rather than as a spreadsheet. And club colour, applied to every
player element (see theme.py) so the app looks like football rather than
a dashboard that happens to be about football.

Colours are the Premier League's published palette — Valentino purple,
Razzmatazz pink and the two FPL accent tones — not approximations.
"""
import pandas as pd
import streamlit as st

from fpl_assistant.dashboard.htmlutil import render_html
from fpl_assistant.dashboard.theme import (
    CYAN,
    GREEN,
    INK_500,
    INK_600,
    INK_700,
    INK_800,
    INK_900,
    PINK,
    PURPLE,
    TEXT,
    TEXT_FAINT,
    TEXT_MUTED,
)

# Barlow Condensed carries headings and numbers: condensed type is what
# makes a scoreline or a price read as sport rather than as data, and it
# lets long player names fit a card without shrinking to unreadable.
# Inter handles body copy, where neutrality and legibility matter more.
FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=Barlow+Condensed:wght@600;700&family=Inter:wght@400;500;600;700&display=swap');"
)
FONT_DISPLAY = "'Barlow Condensed', 'Inter', system-ui, sans-serif"
FONT_BODY = "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"

GLOBAL_CSS = f"""
<style>
{FONT_IMPORT}

/* --- Typography -------------------------------------------------- */
html, body, [class*="css"], .stMarkdown, p, li, div[data-testid="stMetricValue"] {{
    font-family: {FONT_BODY};
}}
h1, h2, h3, h4, .section-banner .title, .hero-title {{
    font-family: {FONT_DISPLAY};
    letter-spacing: 0.01em;
}}
.stMarkdown p {{ line-height: 1.62; }}
/* Long-form rationale sits at a comfortable measure instead of running
   the full width of a desktop window, which is where reading breaks down. */
.stMarkdown p, .stMarkdown li {{ max-width: 78ch; }}

/* --- Metric cards ------------------------------------------------- */
div[data-testid="stMetric"] {{
    background: linear-gradient(160deg, {INK_700}, {INK_800});
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 14px;
    padding: 14px 16px 12px 16px;
    position: relative;
    overflow: hidden;
}}
div[data-testid="stMetric"]::before {{
    content: "";
    position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, {CYAN}, {GREEN});
}}
div[data-testid="stMetricLabel"] {{
    font-size: 11px !important;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: {TEXT_MUTED} !important;
}}
div[data-testid="stMetricValue"] {{
    font-family: {FONT_DISPLAY};
    font-size: 30px !important;
    font-weight: 700;
    /* Tabular figures stop numbers jittering as values change. */
    font-variant-numeric: tabular-nums;
}}

/* --- Tabs ---------------------------------------------------------- */
.stTabs {{ position: relative; }}
.stTabs [data-baseweb="tab-list"] {{
    gap: 2px;
    border-bottom: 1px solid rgba(255,255,255,0.07);
    scrollbar-width: none;
}}
.stTabs [data-baseweb="tab-list"]::-webkit-scrollbar {{ display: none; }}
.stTabs [data-baseweb="tab"] {{
    padding: 9px 16px;
    border-radius: 10px 10px 0 0;
    font-weight: 600;
    font-size: 14px;
    color: {TEXT_MUTED};
}}
.stTabs [aria-selected="true"] {{
    background: linear-gradient(180deg, rgba(4,245,255,0.10), rgba(4,245,255,0.02));
    color: {TEXT};
}}
.stTabs [data-baseweb="tab-highlight"] {{ background-color: {GREEN} !important; }}
.stTabs::after {{
    content: "";
    position: absolute; top: 0; right: 0;
    width: 28px; height: 42px;
    background: linear-gradient(to right, rgba(11,11,20,0), rgba(11,11,20,0.95));
    pointer-events: none;
}}

/* --- Surfaces ------------------------------------------------------ */
div[data-testid="stDataFrame"] {{
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid rgba(255,255,255,0.07);
}}
div[data-testid="stExpander"] {{
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 12px;
    background: {INK_800};
    margin-bottom: 8px;
}}
div[data-testid="stExpander"] summary {{ font-weight: 600; }}
div[data-testid="stExpander"] summary:hover {{ color: {CYAN}; }}

section[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, {INK_800}, {INK_900});
    border-right: 1px solid rgba(255,255,255,0.06);
}}

/* --- Section banner ------------------------------------------------ */
.section-banner {{
    display: flex;
    align-items: baseline;
    gap: 10px;
    flex-wrap: wrap;
    margin: 18px 0 14px 0;
    padding-bottom: 8px;
    border-bottom: 1px solid rgba(255,255,255,0.07);
}}
.section-banner .title {{
    font-size: 25px;
    font-weight: 700;
    color: {TEXT};
    letter-spacing: 0.005em;
}}
.section-banner .subtitle {{
    font-size: 12.5px;
    color: {TEXT_FAINT};
}}

/* --- Chrome -------------------------------------------------------- */
#MainMenu {{ visibility: hidden; }}
footer {{ visibility: hidden; }}

.rank-card, .player-card {{
    transition: transform 0.14s ease, box-shadow 0.14s ease, border-color 0.14s ease;
}}
.rank-card:hover {{
    transform: translateY(-1px);
    border-color: rgba(0,255,133,0.35);
}}
.player-card:hover {{
    transform: translateY(-2px);
    box-shadow: 0 8px 20px rgba(0,0,0,0.55);
}}

.stButton button {{
    border-radius: 10px !important;
    font-weight: 600;
    border: 1px solid rgba(255,255,255,0.12) !important;
    transition: border-color 0.14s ease, transform 0.1s ease;
}}
.stButton button:hover {{
    border-color: {CYAN} !important;
    transform: translateY(-1px);
}}
.stSelectbox div[data-baseweb="select"] > div,
.stTextArea textarea,
.stTextInput input {{
    border-radius: 10px !important;
}}

/* Numbers in tables should line up column-to-column. */
div[data-testid="stDataFrame"] td {{ font-variant-numeric: tabular-nums; }}
</style>
"""

HERO_HTML = f"""
<div class="pl-hero">
  <div class="pl-hero-bar"></div>
  <div class="hero-title">FPL Assistant Manager</div>
  <div class="pl-hero-sub">
    Projections · Expert consensus · Captaincy · Transfers — one view per gameweek
  </div>
</div>
<style>
.pl-hero {{
    position: relative;
    overflow: hidden;
    border-radius: 18px;
    padding: 26px 28px 22px 28px;
    margin-bottom: 20px;
    background:
        radial-gradient(120% 140% at 0% 0%, rgba(233,0,82,0.20) 0%, transparent 55%),
        radial-gradient(120% 140% at 100% 0%, rgba(4,245,255,0.16) 0%, transparent 55%),
        linear-gradient(135deg, {PURPLE} 0%, {INK_700} 55%, {INK_900} 100%);
    border: 1px solid rgba(255,255,255,0.09);
}}
.pl-hero-bar {{
    position: absolute; top: 0; left: 0; right: 0; height: 3px;
    background: linear-gradient(90deg, {CYAN}, {GREEN}, {PINK});
}}
.pl-hero .hero-title {{
    font-size: 40px;
    font-weight: 700;
    line-height: 1.05;
    color: #ffffff;
    text-transform: uppercase;
    letter-spacing: 0.015em;
}}
.pl-hero-sub {{
    font-size: 13px;
    color: rgba(255,255,255,0.62);
    margin-top: 6px;
    letter-spacing: 0.01em;
}}
@media (max-width: 640px) {{
    .pl-hero {{ padding: 20px 18px 16px 18px; }}
    .pl-hero .hero-title {{ font-size: 30px; }}
}}
</style>
"""

def inject_global_css() -> None:
    render_html(GLOBAL_CSS)


def hero_header() -> None:
    render_html(HERO_HTML)


def section_header(title: str, subtitle: str = "") -> None:
    subtitle_html = f'<span class="subtitle">{subtitle}</span>' if subtitle else ""
    render_html(f'<div class="section-banner"><span class="title">{title}</span>{subtitle_html}</div>')


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

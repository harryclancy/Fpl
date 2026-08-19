"""The app's stylesheet: typography, surfaces, and the component CSS
layered over the light base theme in .streamlit/config.toml.

Designing on white is not the dark theme inverted. Three things had to
change rather than flip:

  Colour   the neon green and cyan that carried the dark UI fail contrast
           on white, so the accent role moves to Premier League purple and
           green survives only as a tint behind darker text.
  Depth    dark themes separate surfaces with lighter fills; light ones
           can't, because there's nothing lighter than white. Separation
           comes from hairline borders and very soft shadows instead.
  Weight   the same type looks heavier on white, so weights come down a
           step and letter-spacing opens slightly.

Type pairs a condensed display face for headings and figures with a
neutral UI face for prose — the pairing sports broadcasters use, and
condensed type lets a long player name fit a card without shrinking.
"""
import pandas as pd
import streamlit as st

from fpl_assistant.dashboard.htmlutil import render_html
from fpl_assistant.dashboard.theme import (
    ACCENT_TINT,
    BORDER,
    BORDER_STRONG,
    CYAN,
    GREEN,
    NEGATIVE,
    NEGATIVE_TINT,
    PAPER,
    PINK,
    POSITIVE,
    POSITIVE_TINT,
    PURPLE,
    SURFACE_50,
    SURFACE_100,
    SURFACE_200,
    TEXT,
    TEXT_FAINT,
    TEXT_MUTED,
    WARNING,
    WARNING_TINT,
)

FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=Barlow+Condensed:wght@600;700&family=Inter:wght@400;500;600;700&display=swap');"
)
FONT_DISPLAY = "'Barlow Condensed', 'Inter', system-ui, sans-serif"
FONT_BODY = "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"

# Soft, low-contrast shadows. On white, a shadow dark enough to notice
# reads as grubby — depth has to come mostly from the border, with the
# shadow only hinting at lift.
SHADOW_SM = "0 1px 2px rgba(21,19,26,0.04), 0 1px 1px rgba(21,19,26,0.03)"
SHADOW_MD = "0 2px 6px rgba(21,19,26,0.06), 0 1px 2px rgba(21,19,26,0.04)"
SHADOW_LG = "0 8px 24px rgba(21,19,26,0.09), 0 2px 6px rgba(21,19,26,0.05)"

GLOBAL_CSS = f"""
<style>
{FONT_IMPORT}

/* --- Base ---------------------------------------------------------- */
html, body, [class*="css"], .stMarkdown, p, li, input, textarea, button {{
    font-family: {FONT_BODY};
    -webkit-font-smoothing: antialiased;
}}
.stApp {{ background: {PAPER}; }}
h1, h2, h3, h4, .section-banner .title, .hero-title {{
    font-family: {FONT_DISPLAY};
    letter-spacing: 0.005em;
    color: {TEXT};
}}
.stMarkdown p {{ line-height: 1.65; color: {TEXT}; }}
/* Long-form rationale sits at a comfortable measure rather than running
   the full width of a desktop window, which is where reading breaks. */
.stMarkdown p, .stMarkdown li {{ max-width: 76ch; }}
.block-container {{ padding-top: 2.2rem; max-width: 1180px; }}

/* --- Metric cards --------------------------------------------------- */
div[data-testid="stMetric"] {{
    background: {PAPER};
    border: 1px solid {BORDER};
    border-radius: 14px;
    padding: 15px 18px 13px 18px;
    box-shadow: {SHADOW_SM};
    position: relative;
    overflow: hidden;
    transition: box-shadow 0.16s ease, border-color 0.16s ease;
}}
div[data-testid="stMetric"]:hover {{
    box-shadow: {SHADOW_MD};
    border-color: {BORDER_STRONG};
}}
div[data-testid="stMetric"]::before {{
    content: "";
    position: absolute; top: 0; left: 0; right: 0; height: 3px;
    background: linear-gradient(90deg, {PURPLE}, {PINK});
}}
div[data-testid="stMetricLabel"] {{
    font-size: 11px !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 600;
    color: {TEXT_MUTED} !important;
}}
div[data-testid="stMetricValue"] {{
    font-family: {FONT_DISPLAY};
    font-size: 32px !important;
    font-weight: 700;
    color: {TEXT};
    /* Tabular figures stop numbers jittering as values change. */
    font-variant-numeric: tabular-nums;
    /* Streamlit truncates long metric values with an ellipsis, which turned
       the captain's name into "Haaland…" — the one thing on that card you
       actually need to read. Let it wrap instead. */
    white-space: normal;
    overflow: visible;
    text-overflow: clip;
    line-height: 1.1;
}}
div[data-testid="stMetricValue"] > div {{ overflow: visible; white-space: normal; }}

/* --- Tabs ----------------------------------------------------------- */
.stTabs {{ position: relative; }}
.stTabs [data-baseweb="tab-list"] {{
    gap: 2px;
    border-bottom: 1px solid {BORDER};
    scrollbar-width: none;
}}
.stTabs [data-baseweb="tab-list"]::-webkit-scrollbar {{ display: none; }}
.stTabs [data-baseweb="tab"] {{
    padding: 10px 16px;
    border-radius: 10px 10px 0 0;
    font-weight: 600;
    font-size: 14px;
    color: {TEXT_MUTED};
    transition: color 0.14s ease, background 0.14s ease;
}}
.stTabs [data-baseweb="tab"]:hover {{ color: {PURPLE}; background: {SURFACE_50}; }}
.stTabs [aria-selected="true"] {{ color: {PURPLE}; background: {ACCENT_TINT}; }}
.stTabs [data-baseweb="tab-highlight"] {{ background-color: {PURPLE} !important; }}
.stTabs::after {{
    content: "";
    position: absolute; top: 0; right: 0;
    width: 24px; height: 44px;
    background: linear-gradient(to right, rgba(255,255,255,0), {PAPER});
    pointer-events: none;
}}

/* --- Surfaces -------------------------------------------------------- */
div[data-testid="stDataFrame"] {{
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid {BORDER};
    box-shadow: {SHADOW_SM};
}}
div[data-testid="stDataFrame"] td {{ font-variant-numeric: tabular-nums; }}

div[data-testid="stExpander"] {{
    border: 1px solid {BORDER};
    border-radius: 12px;
    background: {PAPER};
    margin-bottom: 10px;
    box-shadow: {SHADOW_SM};
    transition: box-shadow 0.16s ease, border-color 0.16s ease;
}}
div[data-testid="stExpander"]:hover {{
    border-color: {BORDER_STRONG};
    box-shadow: {SHADOW_MD};
}}
div[data-testid="stExpander"] summary {{ font-weight: 600; color: {TEXT}; }}
div[data-testid="stExpander"] summary:hover {{ color: {PURPLE}; }}

section[data-testid="stSidebar"] {{
    background: {SURFACE_50};
    border-right: 1px solid {BORDER};
}}
section[data-testid="stSidebar"] .stMarkdown p {{ color: {TEXT_MUTED}; }}

/* --- Section banner --------------------------------------------------- */
.section-banner {{
    display: flex;
    align-items: baseline;
    gap: 10px;
    flex-wrap: wrap;
    margin: 22px 0 14px 0;
    padding-bottom: 9px;
    border-bottom: 1px solid {BORDER};
}}
.section-banner .title {{ font-size: 26px; font-weight: 700; }}
.section-banner .subtitle {{ font-size: 12.5px; color: {TEXT_FAINT}; }}

/* --- Controls --------------------------------------------------------- */
.stButton button {{
    border-radius: 10px !important;
    font-weight: 600;
    border: 1px solid {BORDER_STRONG} !important;
    background: {PAPER};
    color: {TEXT};
    transition: all 0.14s ease;
    box-shadow: {SHADOW_SM};
}}
.stButton button:hover {{
    border-color: {PURPLE} !important;
    color: {PURPLE};
    transform: translateY(-1px);
    box-shadow: {SHADOW_MD};
}}
.stButton button[kind="primary"] {{
    background: {PURPLE};
    color: #ffffff;
    border-color: {PURPLE} !important;
}}
.stButton button[kind="primary"]:hover {{
    background: #4a0050;
    color: #ffffff;
}}
.stSelectbox div[data-baseweb="select"] > div,
.stTextArea textarea,
.stTextInput input {{
    border-radius: 10px !important;
    border-color: {BORDER_STRONG} !important;
    background: {PAPER} !important;
}}
.stSelectbox div[data-baseweb="select"] > div:focus-within,
.stTextInput input:focus {{
    border-color: {PURPLE} !important;
    box-shadow: 0 0 0 3px {ACCENT_TINT} !important;
}}
.stRadio [role="radiogroup"] label {{ color: {TEXT}; }}

/* --- Callouts --------------------------------------------------------- */
div[data-testid="stAlert"] {{
    border-radius: 12px;
    border: 1px solid {BORDER};
    box-shadow: {SHADOW_SM};
}}

/* Streamlit renders spinners as a floating overlay; soften it so a
   three-second solve doesn't feel like the page broke. */
div[data-testid="stSpinner"] {{ color: {TEXT_MUTED}; }}

/* --- Chrome ----------------------------------------------------------- */
#MainMenu {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
header[data-testid="stHeader"] {{ background: transparent; }}

.rank-card, .player-card {{
    transition: transform 0.14s ease, box-shadow 0.14s ease, border-color 0.14s ease;
}}
.rank-card:hover {{
    transform: translateY(-1px);
    border-color: {BORDER_STRONG};
    box-shadow: {SHADOW_MD};
}}
.player-card:hover {{
    transform: translateY(-2px);
    box-shadow: {SHADOW_LG};
}}

/* --- Semantic pills ---------------------------------------------------- */
.pill {{
    display: inline-block;
    padding: 2px 9px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.01em;
    line-height: 1.6;
}}
.pill-good {{ background: {POSITIVE_TINT}; color: {POSITIVE}; }}
.pill-warn {{ background: {WARNING_TINT}; color: {WARNING}; }}
.pill-bad {{ background: {NEGATIVE_TINT}; color: {NEGATIVE}; }}
.pill-accent {{ background: {ACCENT_TINT}; color: {PURPLE}; }}
</style>
"""

HERO_HTML = f"""
<div class="pl-hero">
  <div class="pl-hero-bar"></div>
  <div class="hero-title">FPL Assistant Manager</div>
  <div class="pl-hero-sub">
    Projections · Expert consensus · Captaincy · Chips · Transfers
  </div>
</div>
<style>
.pl-hero {{
    position: relative;
    overflow: hidden;
    border-radius: 18px;
    padding: 30px 30px 26px 30px;
    margin-bottom: 22px;
    background:
        radial-gradient(120% 160% at 100% 0%, rgba(233,0,82,0.16) 0%, transparent 60%),
        linear-gradient(135deg, {PURPLE} 0%, #4b0a52 55%, #2b0030 100%);
    box-shadow: {SHADOW_LG};
}}
.pl-hero-bar {{
    position: absolute; top: 0; left: 0; right: 0; height: 3px;
    background: linear-gradient(90deg, {CYAN}, {GREEN}, {PINK});
}}
.pl-hero .hero-title {{
    font-size: 42px;
    font-weight: 700;
    line-height: 1.02;
    color: #ffffff;
    text-transform: uppercase;
    letter-spacing: 0.015em;
}}
.pl-hero-sub {{
    font-size: 13px;
    color: rgba(255,255,255,0.72);
    margin-top: 7px;
    letter-spacing: 0.02em;
}}
@media (max-width: 640px) {{
    .pl-hero {{ padding: 22px 18px 18px 18px; }}
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


# Fixture difficulty, as tints rather than saturated fills. On white, a
# solid red cell is louder than the information deserves and drags the eye
# away from everything else on the page.
_FDR_STOPS = [(1, (10, 125, 79)), (3, (138, 90, 0)), (5, (176, 32, 60))]


def fdr_color(value: float) -> str:
    """Background style for a fixture-difficulty value (1 easiest, 5 hardest).

    Interpolated green → amber → red, applied as a pale tint with the
    matching dark text on top so it stays readable and keeps its meaning
    for anyone who can't separate the hues.
    """
    if pd.isna(value):
        return ""
    value = min(max(value, 1), 5)
    lo, hi = (_FDR_STOPS[0], _FDR_STOPS[1]) if value <= 3 else (_FDR_STOPS[1], _FDR_STOPS[2])
    span = hi[0] - lo[0]
    t = 0.0 if span == 0 else (value - lo[0]) / span
    rgb = tuple(round(lo[1][i] + t * (hi[1][i] - lo[1][i])) for i in range(3))
    return (
        f"background-color: rgba({rgb[0]},{rgb[1]},{rgb[2]},0.14); "
        f"color: rgb({rgb[0]},{rgb[1]},{rgb[2]}); font-weight: 700;"
    )

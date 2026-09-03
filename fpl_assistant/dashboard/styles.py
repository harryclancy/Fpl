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

/* On a phone Streamlit stacks columns full-width, so a four-metric row
   becomes a four-screen scroll before you reach the actual squad. Two up
   keeps the whole summary visible in one glance, which is the only reason
   the row exists. */
@media (max-width: 640px) {{
    div[data-testid="stHorizontalBlock"] {{
        flex-wrap: wrap;
        gap: 8px;
    }}
    div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {{
        flex: 1 1 calc(50% - 8px);
        min-width: calc(50% - 8px);
        width: auto;
    }}
    /* Long player names are the widest thing these cards ever hold, so
       the mobile size is set by what fits a surname rather than by what
       looks biggest. */
    div[data-testid="stMetricValue"] {{ font-size: 22px !important; }}
    div[data-testid="stMetricValue"] p {{ overflow-wrap: break-word; }}
    .block-container {{ padding-top: 1.2rem; }}
}}

/* Streamlit truncates both the metric label and its value with an
   ellipsis once the column is narrow — on a phone that produced
   "Projected GW …" and "Haaland…", losing the only words that mattered.
   The clipping lives on the inner <p>, not on the testid'd wrappers, so
   overriding the wrappers alone (the obvious fix) changes nothing
   visible: the DOM text reads in full while the screen still shows an
   ellipsis. Every level has to be unset. */
div[data-testid="stMetricValue"],
div[data-testid="stMetricValue"] div,
div[data-testid="stMetricValue"] p,
div[data-testid="stMetricLabel"],
div[data-testid="stMetricLabel"] div,
div[data-testid="stMetricLabel"] p {{
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: clip !important;
}}
div[data-testid="stMetricLabel"] p {{ line-height: 1.35; }}
div[data-testid="stMetric"] {{ overflow: visible; }}

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


# Mobile-first overrides for the homepage.
#
# The site is read on a phone, standing up, shortly before a deadline. That
# is a different reading situation from a desktop dashboard and it wants
# different things: one column, big type, generous spacing, and the squad
# visible without scrolling past anything else.
#
# Everything here is written as a widening rather than a shrinking — the
# base layout IS the phone layout, and the desktop gets a max-width. Doing
# it the other way round is how a dashboard ends up squeezed onto a screen
# it was never designed for.
HOMEPAGE_CSS = """
<style>
/* One column, always. Streamlit's horizontal columns become stacked
   blocks below tablet width so nothing is ever a tiny side-by-side. */
@media (max-width: 760px) {
  div[data-testid="stHorizontalBlock"] { flex-direction: column; gap: 0.4rem; }
  div[data-testid="stHorizontalBlock"] > div { width: 100% !important; flex: 1 1 100% !important; }
  .block-container { padding-left: 0.9rem; padding-right: 0.9rem; padding-top: 1rem; }
}

/* Readable at arm's length. 17px is the smallest that stays comfortable
   on a phone in daylight. */
.fpl-home .stMarkdown p, .fpl-home .stMarkdown li {
  font-size: 1.02rem; line-height: 1.62; max-width: 68ch;
}

/* Section headings that actually separate sections. */
.fpl-section {
  font-family: 'Barlow Condensed', system-ui, sans-serif;
  font-size: 1.55rem; font-weight: 700; letter-spacing: .02em;
  text-transform: uppercase; margin: 2.4rem 0 .2rem 0; color: #10121a;
}
.fpl-section:first-of-type { margin-top: .6rem; }
.fpl-sub { color: #6b7280; font-size: .93rem; margin: 0 0 1rem 0; }

/* Cards: rounded, roomy, one per row. */
.fpl-card {
  background: #fff; border: 1px solid #e8e6ef; border-radius: 16px;
  padding: 1.05rem 1.15rem; margin: 0 0 .85rem 0;
  box-shadow: 0 1px 2px rgba(16,18,26,.04);
}
.fpl-card h4 { margin: 0 0 .1rem 0; font-size: 1.12rem; letter-spacing: .01em; }
.fpl-meta { color: #6b7280; font-size: .87rem; margin: 0 0 .6rem 0; }

/* The transfer block: vertical, with the arrow doing the work. */
.fpl-swap { text-align: center; margin: .2rem 0 .9rem 0; }
.fpl-swap .leg { font-size: 1.24rem; font-weight: 700; }
.fpl-swap .lab { font-size: .74rem; letter-spacing: .14em; color: #6b7280; text-transform: uppercase; }
.fpl-swap .arrow { font-size: 1.5rem; color: #9aa0ac; line-height: 1.1; margin: .15rem 0; }
.fpl-out .leg { color: #b4232a; }
.fpl-in  .leg { color: #0f7b3f; }

/* Confidence pill. */
.fpl-pill {
  display: inline-block; padding: .16rem .6rem; border-radius: 999px;
  font-size: .76rem; font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
}
.fpl-high { background: #e6f4ec; color: #0f7b3f; }
.fpl-med  { background: #fdf3e3; color: #9a6400; }
.fpl-low  { background: #fdeaea; color: #b4232a; }

/* Keep anything wide inside its own scroller so the page never does. */
.fpl-home table, .fpl-home pre { display: block; overflow-x: auto; max-width: 100%; }

/* ------------------------------------------------------------------ */
/* THE DESIGN SYSTEM                                                    */
/*                                                                      */
/* Colour carries meaning here and nothing else. A premium sports        */
/* product is restrained: one deep near-black for structure, one violet  */
/* accent for the app's own voice, and three status colours that mean    */
/* exactly one thing each wherever they appear. Everything else is       */
/* neutral, so when something IS coloured the eye knows it matters.      */
.fpl-home {
  --ink: #14161f;           /* deep navy-black: structure and headings  */
  --ink-2: #2a2e3d;
  --grey: #6b7280;          /* cool grey: secondary text                */
  --grey-2: #9aa1ad;
  --line: #e7e6ee;
  --surface: #ffffff;
  --surface-2: #f7f7fb;
  --accent: #6d5ae6;        /* violet: the app speaking, never a status */
  --accent-soft: #efecfe;
  --good: #14794a;          /* muted green: secure, positive            */
  --good-soft: #e7f4ed;
  --warn: #9a6400;          /* amber: monitor, uncertain                */
  --warn-soft: #fdf3e3;
  --bad: #a8232c;           /* muted red: doubt, sell, unavailable      */
  --bad-soft: #fbeaec;
}

/* --- the player row: one tap target, everything on it ------------- */
/* Fifteen of these are the page. They have to be scannable in a       */
/* column on a phone, which means a fixed height, a real photo, and    */
/* the three things a manager checks before a deadline: what the plan  */
/* says, whether he plays, and how sure it is.                         */
.fpl-prow {
  display: flex; align-items: center; gap: .8rem;
  padding: .1rem 0;
}
.fpl-prow .face { flex: 0 0 auto; }
.fpl-prow .body { flex: 1 1 auto; min-width: 0; }
.fpl-prow .name {
  font-family: 'Barlow Condensed', system-ui, sans-serif;
  font-size: 1.28rem; font-weight: 700; letter-spacing: .01em;
  color: var(--ink); line-height: 1.1; text-transform: uppercase;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.fpl-prow .sub {
  color: var(--grey); font-size: .82rem; margin-top: .1rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.fpl-prow .tags { margin-top: .34rem; display: flex; flex-wrap: wrap; gap: .3rem; }
.fpl-prow .fx {
  flex: 0 0 auto; text-align: right; color: var(--grey);
  font-size: .78rem; line-height: 1.3;
}
.fpl-prow .fx b { display: block; color: var(--ink-2); font-size: .92rem; }

/* --- tags: the only coloured things in a player row ---------------- */
.fpl-tag {
  display: inline-block; padding: .14rem .5rem; border-radius: 6px;
  font-size: .69rem; font-weight: 700; letter-spacing: .05em;
  text-transform: uppercase; white-space: nowrap;
}
.t-good { background: var(--good-soft); color: var(--good); }
.t-warn { background: var(--warn-soft); color: var(--warn); }
.t-bad  { background: var(--bad-soft);  color: var(--bad); }
.t-flat { background: var(--surface-2); color: var(--grey);
          border: 1px solid var(--line); }
.t-accent { background: var(--accent-soft); color: var(--accent); }

/* --- the four sections inside an opened player -------------------- */
.fpl-lead {
  font-size: 1rem; line-height: 1.6; color: var(--ink-2);
  border-left: 3px solid var(--accent); padding-left: .8rem;
  margin: .2rem 0 .9rem 0;
}
.fpl-verdict {
  background: var(--surface-2); border: 1px solid var(--line);
  border-radius: 12px; padding: .7rem .85rem; margin: .2rem 0 .4rem 0;
}
.fpl-verdict .label {
  font-family: 'Barlow Condensed', system-ui, sans-serif;
  font-size: 1.05rem; font-weight: 700; letter-spacing: .04em;
  text-transform: uppercase; color: var(--ink);
}

/* --- the next four, as a strip -------------------------------------- */
.fpl-run { display: flex; gap: .34rem; margin: .1rem 0 .5rem 0; flex-wrap: wrap; }
.fpl-run span {
  flex: 1 1 0; min-width: 62px; text-align: center;
  background: var(--surface-2); border: 1px solid var(--line);
  border-radius: 8px; padding: .3rem .2rem;
  font-size: .78rem; font-weight: 600; color: var(--ink-2);
}

/* --- the question box ----------------------------------------------- */
.fpl-ask { margin-top: .4rem; }
.fpl-ask-answer {
  background: var(--surface); border: 1px solid var(--line);
  border-left: 3px solid var(--accent);
  border-radius: 12px; padding: .85rem 1rem; margin: .6rem 0;
}
.fpl-ask-answer h5 {
  font-family: 'Barlow Condensed', system-ui, sans-serif;
  margin: 0 0 .3rem 0; font-size: 1.12rem; letter-spacing: .03em;
  text-transform: uppercase; color: var(--ink);
}

/* Streamlit's expander, made to read as a row rather than a widget. */
.fpl-home div[data-testid="stExpander"] details {
  border: 1px solid var(--line) !important; border-radius: 14px !important;
  background: var(--surface) !important; margin-bottom: .55rem !important;
  box-shadow: 0 1px 2px rgba(16,18,26,.04);
}
.fpl-home div[data-testid="stExpander"] summary { padding: .6rem .8rem !important; }
.fpl-home div[data-testid="stExpander"] summary:hover { background: var(--surface-2) !important; }
</style>
"""


def inject_homepage_css() -> None:
    render_html(HOMEPAGE_CSS)


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

"""Shared visual styling for the dashboard: a hero header and small CSS
tweaks layered on top of the dark theme set in .streamlit/config.toml.
"""
import streamlit as st

GLOBAL_CSS = """
<style>
/* Metric cards */
div[data-testid="stMetric"] {
    background: linear-gradient(145deg, #171729, #1d1d36);
    border: 1px solid rgba(255,255,255,0.08);
    border-left: 3px solid #00ff87;
    border-radius: 12px;
    padding: 14px 16px 10px 16px;
}
div[data-testid="stMetricLabel"] { opacity: 0.75; }

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
}
.stTabs [data-baseweb="tab"] {
    padding: 8px 16px;
    border-radius: 8px 8px 0 0;
}
.stTabs [aria-selected="true"] {
    background: rgba(0,255,135,0.08);
}

/* Dataframes / tables */
div[data-testid="stDataFrame"] {
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid rgba(255,255,255,0.08);
}

/* Section headers get a little breathing room */
h2, h3 { margin-top: 0.4em; }

/* Hide the default Streamlit chrome that adds noise on mobile */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
</style>
"""

HERO_HTML = """
<div style="
    background: linear-gradient(120deg, #37003c 0%, #1d1d36 60%, #0e0e1a 100%);
    border-radius: 16px;
    padding: 22px 26px;
    margin-bottom: 18px;
    border: 1px solid rgba(0,255,135,0.25);
">
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

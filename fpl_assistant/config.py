import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _get_team_id() -> str | None:
    team_id = os.environ.get("FPL_TEAM_ID")
    if team_id:
        return team_id
    # On Streamlit Community Cloud, config comes from the app's Secrets
    # manager (st.secrets) rather than a real .env file.
    try:
        import streamlit as st

        return st.secrets.get("FPL_TEAM_ID")
    except Exception:
        return None


FPL_TEAM_ID = _get_team_id()

BASE_URL = "https://fantasy.premierleague.com/api"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# How long cached API responses stay fresh before we refetch.
CACHE_TTL_SECONDS = {
    "bootstrap-static": 60 * 30,  # prices/injury news change a few times a day
    "fixtures": 60 * 60 * 6,
    "entry": 60 * 10,
    "live": 60 * 5,
}

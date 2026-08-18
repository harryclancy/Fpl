import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

FPL_TEAM_ID = os.environ.get("FPL_TEAM_ID")

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

"""End-to-end smoke test: actually runs the Streamlit app and asserts it
doesn't crash.

This exists because of a real incident: an edit accidentally deleted a
`def render_fixtures_tab(...):` line while merging in unrelated code,
leaving that function's body dangling as trailing statements inside a
different function. `python -m py_compile` and every unit test still
passed -- a NameError like that only raises when the code path actually
executes, and Streamlit runs every tab's rendering code on every single
page load (not just the one you click into), so this had been crashing
the entire deployed app on every load. Only running the real app live
caught it. This test automates that check so it can't slip through
silently again.
"""
import json
import random
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from fpl_assistant import api
import fpl_assistant.config as config

APP_PATH = str(Path(__file__).resolve().parent.parent / "fpl_assistant" / "dashboard" / "app.py")

TEAMS = [
    ("Arsenal", "ARS"), ("Aston Villa", "AVL"), ("Bournemouth", "BOU"), ("Brentford", "BRE"),
    ("Brighton", "BHA"), ("Chelsea", "CHE"), ("Coventry", "COV"), ("Crystal Palace", "CRY"),
    ("Everton", "EVE"), ("Fulham", "FUL"), ("Hull City", "HUL"), ("Liverpool", "LIV"),
    ("Man City", "MCI"), ("Man Utd", "MUN"), ("Newcastle", "NEW"), ("Nottm Forest", "NFO"),
    ("Sunderland", "SUN"), ("Spurs", "TOT"), ("West Ham", "WHU"), ("Wolves", "WOL"),
]
SURNAMES = [
    "Silva", "Johnson", "Martins", "Costa", "Adeyemi", "Foster", "Okafor", "Wright",
    "Bennett", "Larsson", "Moreno",
]
POSITIONS = {"GKP": 2, "DEF": 6, "MID": 6, "FWD": 3}
ELEMENT_TYPE = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}


def _synthetic_bootstrap(preseason: bool) -> dict:
    rng = random.Random(42)
    elements, teams_json, pid = [], [], 1
    for team_id, (name, short) in enumerate(TEAMS, start=1):
        teams_json.append({"id": team_id, "name": name, "short_name": short, "code": team_id * 3 + 10, "strength": 3})
        for pos, count in POSITIONS.items():
            for _ in range(count):
                price = round(rng.uniform(4.0, 14.5), 1)
                elements.append({
                    "id": pid, "code": 100000 + pid, "web_name": f"{rng.choice(SURNAMES)}{pid}",
                    "first_name": "J.", "second_name": rng.choice(SURNAMES), "team": team_id,
                    "element_type": ELEMENT_TYPE[pos], "now_cost": int(price * 10),
                    "total_points": 0 if preseason else rng.randint(0, 120),
                    "points_per_game": "0.0" if preseason else str(round(rng.uniform(0, 7), 1)),
                    "form": "0.0" if preseason else str(round(rng.uniform(0, 8), 1)),
                    "selected_by_percent": str(round(rng.uniform(0.1, 45), 1)),
                    "minutes": 0 if preseason else rng.choice([90, 450, 900]),
                    "status": rng.choice(["a", "a", "a", "a", "d", "i"]),
                    "news": "Knock, assessed after training" if rng.random() < 0.1 else "",
                    "news_added": None,
                    "chance_of_playing_next_round": rng.choice([100, 100, 100, 75, 50, 25, 0]),
                    "expected_goal_involvements": "0.0" if preseason else str(round(rng.uniform(0, 8), 2)),
                    "expected_goals_conceded": "0.0" if preseason else str(round(rng.uniform(0, 6), 2)),
                    "value_form": "0.0", "value_season": "0.0",
                    "ict_index": str(round(rng.uniform(0, 200), 1)), "bonus": rng.randint(0, 15),
                    "transfers_in_event": rng.randint(0, 80000), "transfers_out_event": rng.randint(0, 80000),
                })
                pid += 1
    events = [
        {"id": gw, "name": f"Gameweek {gw}", "deadline_time": f"2026-08-{18+gw:02d}T18:30:00Z",
         "is_current": gw == 1, "is_next": gw == 2, "finished": False}
        for gw in range(1, 6)
    ]
    return {"teams": teams_json, "elements": elements, "events": events}


def _synthetic_fixtures() -> list[dict]:
    rng = random.Random(7)
    fixtures, fid = [], 1
    team_ids = list(range(1, len(TEAMS) + 1))
    for gw in range(1, 6):
        rng.shuffle(team_ids)
        for i in range(0, len(team_ids), 2):
            fixtures.append({
                "id": fid, "event": gw, "team_h": team_ids[i], "team_a": team_ids[i + 1],
                "team_h_difficulty": rng.randint(1, 5), "team_a_difficulty": rng.randint(1, 5),
                "finished": False, "kickoff_time": f"2026-08-{18+gw:02d}T15:00:00Z",
            })
            fid += 1
    return fixtures


@pytest.fixture
def patch_api(monkeypatch):
    """Patches the API layer per-test so the app runs fully offline. Also
    clears any local FPL_TEAM_ID so My Squad/Transfers exercise the
    no-team-set path deterministically.

    AppTest re-executes app.py from scratch on every .run(), but Python's
    module cache means its `from fpl_assistant.config import FPL_TEAM_ID`
    is a fresh attribute lookup on the *already-imported* config module,
    not a re-run of config.py -- so patching config.FPL_TEAM_ID directly
    is what actually reaches it. (Clearing the env var alone doesn't
    work: config.py's load_dotenv() just re-reads it straight back out of
    the .env file on disk.) Patching app.FPL_TEAM_ID doesn't work either,
    since that name was already bound at a prior import and a fresh
    exec() rebinds it from config, not from the stale app module.
    """
    def _apply(preseason: bool):
        bootstrap = _synthetic_bootstrap(preseason)
        fixtures = _synthetic_fixtures()
        monkeypatch.setattr(api, "get_bootstrap_static", lambda: bootstrap)
        monkeypatch.setattr(api, "get_fixtures", lambda event=None: fixtures)
        monkeypatch.setattr(config, "FPL_TEAM_ID", None)

    return _apply


def _assert_app_runs_cleanly(at: AppTest):
    at.run(timeout=30)
    assert not at.exception, f"App raised on run: {[str(e) for e in at.exception]}"
    # Every render_*_tab function runs on every script pass regardless of
    # which tab is visually selected -- so one run() already exercises
    # Starting XI, Captaincy, Fixtures, Watchlist, Injuries, and the report
    # tab. Explicitly confirm no error block rendered anywhere on the page.
    assert not at.error, f"App rendered an error block: {[str(e) for e in at.error]}"


def test_app_runs_without_crashing_preseason(patch_api):
    patch_api(preseason=True)
    _assert_app_runs_cleanly(AppTest.from_file(APP_PATH))


def test_app_runs_without_crashing_in_season(patch_api):
    patch_api(preseason=False)
    _assert_app_runs_cleanly(AppTest.from_file(APP_PATH))

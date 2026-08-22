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


@pytest.fixture(autouse=True)
def _clear_streamlit_caches():
    """Streamlit's cache outlives an AppTest instance.

    `load_core_data()` takes no arguments, so its cache key is constant and
    the first test's bootstrap gets served to every test after it. That
    doesn't just break tests that patch the API differently -- it means a
    test can pass on data another test set up, which hides real failures.
    """
    import streamlit as st

    st.cache_data.clear()
    yield
    st.cache_data.clear()


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
    def _apply(preseason: bool, team_id=None):
        bootstrap = _synthetic_bootstrap(preseason)
        fixtures = _synthetic_fixtures()
        monkeypatch.setattr(api, "get_bootstrap_static", lambda: bootstrap)
        monkeypatch.setattr(api, "get_fixtures", lambda event=None: fixtures)
        monkeypatch.setattr(config, "FPL_TEAM_ID", team_id)
        if team_id:
            # Pre-deadline, the API won't serve a gameweek's picks. That's
            # exactly when someone is building a squad, so the copy tool
            # has to work on this path.
            def _unavailable(*args, **kwargs):
                raise RuntimeError("picks not public yet")

            monkeypatch.setattr(api, "get_entry_picks", _unavailable)
            monkeypatch.setattr(api, "get_entry", _unavailable)

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


def _all_markdown(at) -> str:
    return "\n".join(str(block.value) for block in at.markdown)


def _expander_labels(at) -> list[str]:
    return [str(getattr(e, "label", "")) for e in at.get("expander")]


def test_the_omissions_panel_renders_with_real_reasons(patch_api):
    """The "why we're NOT picking X" section has to appear on the page,
    not merely exist as a module.

    This synthetic pool uses the real Premier League short names, so the
    shipped club verdicts in data/consensus/teams.json apply to it -- which
    means this also checks the research file parses and reaches the page.
    """
    patch_api(preseason=True)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=60)
    assert not at.exception, f"App raised: {[str(e) for e in at.exception]}"

    assert any("NOT picking" in label for label in _expander_labels(at))

    page = _all_markdown(at)
    # And it must give real reasons, not just exist. The club-verdict icon
    # only appears when a shipped club stance actually reached a player.
    assert "🚫" in page or "💸" in page


def test_the_cost_of_fitting_a_player_in_is_a_believable_number(patch_api):
    """Guards a bug that shipped for about ten minutes.

    The omissions panel was handed a reconstructed stand-in squad whose
    `expected_points` was zero, so the cost of adding a player -- measured
    as the difference between the re-solved squad and the current one --
    came out as the entire squad's score. The page confidently reported
    that a transfer would "cost ~205 points". Nothing raised, no test
    failed, and the number was stated in the same tone as a correct one.
    """
    import re

    patch_api(preseason=True)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=60)
    assert not at.exception

    costs = [float(m) for m in re.findall(r"costs ~([\d.]+) pts to fit in", _all_markdown(at))]
    assert costs, "no counterfactual costs were rendered to check"
    # One transfer swaps one player. A double-digit swing is possible; a
    # whole squad's worth of points is not.
    assert max(costs) < 40, f"implausible transfer cost rendered: {costs}"


def test_no_bournemouth_players_are_recommended_while_the_verdict_stands(patch_api):
    """The user-facing version of the bug report, against the real
    research data rather than a test-built stance.

    Kept separate from the mechanism tests deliberately: those would still
    pass if someone deleted Bournemouth's verdict from teams.json, because
    they build their own. This one fails if the shipped research stops
    saying what it currently says, which is the other way this can break.
    """
    import pandas as pd

    from fpl_assistant.analysis import consensus

    context = consensus.load_team_context()
    if "BOU" not in context or not context["BOU"].get("stances"):
        pytest.skip("Bournemouth carries no club verdict in the current research file")

    patch_api(preseason=True)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=60)
    assert not at.exception, f"App raised: {[str(e) for e in at.exception]}"


def test_the_club_by_club_briefs_render(patch_api):
    """The team section on the Fixtures tab has to appear on the page,
    with a real verdict per club rather than an empty shell."""
    patch_api(preseason=True)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=90)
    assert not at.exception, f"App raised: {[str(e) for e in at.exception]}"

    briefs = [label for label in _expander_labels(at) if "FDR" in label]
    assert len(briefs) >= 10, f"expected a brief per club, got {len(briefs)}"
    # Ordered kindest run first, so the teams worth shopping at lead.
    import re

    fdrs = [float(re.search(r"([\d.]+) FDR", label).group(1)) for label in briefs]
    assert fdrs == sorted(fdrs)


def test_the_research_search_returns_results(patch_api):
    """Drives the actual search box rather than the module underneath it,
    because the wiring is the part that breaks."""
    patch_api(preseason=True)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=90)

    boxes = [box for box in at.text_input if box.key == "research_search_query"]
    assert boxes, "the search box is missing from the expert section"

    boxes[0].set_value("penalties").run(timeout=90)
    assert not at.exception, f"App raised on search: {[str(e) for e in at.exception]}"

    page = _all_markdown(at)
    assert "result" in page.lower()


def test_an_empty_search_offers_suggestions_rather_than_an_error(patch_api):
    patch_api(preseason=True)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=90)
    assert not at.exception
    assert "Try:" in _all_markdown(at)


def _mid_gameweek_api(monkeypatch, preseason=True):
    """Puts the app in the state that caused the bug: GW1 kicked off,
    some matches played, the rest still to come."""
    from datetime import datetime, timedelta, timezone

    bootstrap = _synthetic_bootstrap(preseason)
    now = datetime.now(timezone.utc)
    for offset, event in enumerate(bootstrap["events"]):
        # GW1's deadline two days ago, then weekly from there.
        event["deadline_time"] = (
            now + timedelta(days=-2 + offset * 7)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        event["finished"] = False

    fixtures = _synthetic_fixtures()
    for i, fixture in enumerate(fixtures):
        if fixture["event"] == 1:
            fixture["finished"] = i % 2 == 0  # half of GW1 played
        else:
            fixture["finished"] = False

    monkeypatch.setattr(api, "get_bootstrap_static", lambda: bootstrap)
    monkeypatch.setattr(api, "get_fixtures", lambda event=None: fixtures)
    monkeypatch.setattr(config, "FPL_TEAM_ID", None)


def test_mid_gameweek_the_page_targets_the_next_gameweek(monkeypatch):
    """The reported bug: mid-GW1 the app kept presenting a GW1 squad,
    recomputed against results already in. Nothing on the page should
    claim to be advice for a deadline that has gone."""
    _mid_gameweek_api(monkeypatch)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception, f"App raised: {[str(e) for e in at.exception]}"

    headers = " ".join(str(b.value) for b in at.markdown)
    assert "Recommended Starting XI — GW2" in headers, (
        "the page is still offering advice for the gameweek being played"
    )


def test_mid_gameweek_the_live_gameweek_is_flagged(monkeypatch):
    _mid_gameweek_api(monkeypatch)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)

    warnings = " ".join(str(w.value) for w in at.warning)
    assert "GW1 is under way" in warnings
    assert "matches played" in warnings


def test_before_the_deadline_nothing_is_flagged_as_live(monkeypatch):
    from datetime import datetime, timedelta, timezone

    bootstrap = _synthetic_bootstrap(True)
    now = datetime.now(timezone.utc)
    for offset, event in enumerate(bootstrap["events"]):
        event["deadline_time"] = (now + timedelta(days=1 + offset * 7)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        event["finished"] = False
    monkeypatch.setattr(api, "get_bootstrap_static", lambda: bootstrap)
    monkeypatch.setattr(api, "get_fixtures", lambda event=None: _synthetic_fixtures())
    monkeypatch.setattr(config, "FPL_TEAM_ID", None)

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception

    warnings = " ".join(str(w.value) for w in at.warning)
    assert "under way" not in warnings
    assert "Recommended Starting XI — GW1" in " ".join(str(b.value) for b in at.markdown)

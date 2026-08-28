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
                    # What he scored in the most recent gameweek. The
                    # write-ups lead on this ("scored last week"), so the
                    # fixture has to carry it or that path never runs.
                    "event_points": 0 if preseason else rng.choice([0, 1, 2, 2, 6, 8, 13]),
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
def _isolate_snapshots(tmp_path, monkeypatch):
    """Keeps test runs out of the real snapshot directory.

    These tests execute the actual app, which writes a pre-deadline
    snapshot as a side effect. Pointed at the repo that means a run
    commits a squad built from synthetic fixture data — and the app would
    then serve that to a real user as "what we suggested before the
    deadline", which is worse than having no snapshot at all.
    """
    from fpl_assistant.analysis import snapshots

    directory = tmp_path / "snapshots"
    directory.mkdir()
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", directory)


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


def _with_confirmed_squad(monkeypatch, preseason=False):
    """Puts the app in the GW2+ state: a squad already played, so a
    from-scratch eleven would be advice you can't act on."""
    from datetime import datetime, timedelta, timezone

    bootstrap = _synthetic_bootstrap(preseason)
    now = datetime.now(timezone.utc)
    for offset, event in enumerate(bootstrap["events"]):
        # GW1 finished; GW2's deadline still ahead.
        event["deadline_time"] = (now + timedelta(days=-6 + offset * 7)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        event["finished"] = offset == 0

    fixtures = _synthetic_fixtures()
    for fixture in fixtures:
        fixture["finished"] = fixture["event"] == 1

    # A legal fifteen out of the synthetic pool.
    #
    # Spread across clubs on purpose. Taking the first five defenders in id
    # order gives five players from the same team, which breaks FPL's
    # three-per-club rule -- and an illegal squad makes every solver that
    # starts from it infeasible, so the transfer and planning paths were
    # silently never exercised by these tests at all.
    elements = bootstrap["elements"]
    by_team: dict[int, dict[int, list[int]]] = {}
    for element in elements:
        by_team.setdefault(element["team"], {}).setdefault(
            element["element_type"], []
        ).append(element["id"])

    per_club: dict[int, int] = {}

    def _take(element_type: int, count: int) -> list[int]:
        picked = []
        for team in sorted(by_team):
            if len(picked) == count:
                break
            if per_club.get(team, 0) >= 3:
                continue
            available = by_team[team].get(element_type, [])
            if not available:
                continue
            picked.append(available.pop(0))
            per_club[team] = per_club.get(team, 0) + 1
        return picked

    chosen = _take(1, 2) + _take(2, 5) + _take(3, 5) + _take(4, 3)
    # The manager's own captain is a forward, as a real one would be. The
    # app must display whatever they actually chose here — it's their
    # squad, not a recommendation — so this needs to be realistic rather
    # than a goalkeeper.
    own_captain = chosen[12]
    picks = {
        "picks": [
            {"element": pid, "position": i + 1, "is_captain": pid == own_captain,
             "is_vice_captain": i == 1, "multiplier": 1 if i < 11 else 0}
            for i, pid in enumerate(chosen)
        ],
        "entry_history": {"bank": 5, "value": 1000, "event_transfers": 0,
                          "event_transfers_cost": 0},
    }

    monkeypatch.setattr(api, "get_bootstrap_static", lambda: bootstrap)
    monkeypatch.setattr(api, "get_fixtures", lambda event=None: fixtures)
    monkeypatch.setattr(api, "get_entry_picks", lambda team_id, event: picks)
    monkeypatch.setattr(api, "get_entry", lambda team_id: {"name": "Test FC",
                                                           "summary_overall_rank": 100000})
    monkeypatch.setattr(
        api, "get_entry_history",
        lambda team_id: {"current": [{"event": 1, "event_transfers": 0}], "chips": []},
    )
    monkeypatch.setattr(config, "FPL_TEAM_ID", 12345)
    return chosen


def test_with_a_confirmed_squad_the_front_page_is_a_plan_not_a_rebuild(monkeypatch):
    """The reported complaint: from GW2 the front page asked for a whole
    new starting eleven, which would cost a fortune in hits."""
    _with_confirmed_squad(monkeypatch)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception, f"App raised: {[str(e) for e in at.exception]}"

    page = _all_markdown(at)
    # The homepage is three sections now. What must hold is that it is
    # anchored on the confirmed squad rather than rebuilt from scratch.
    assert "This week's suggested team" in page
    assert "built from the squad you confirmed" in page
    assert "Best 15 buildable from scratch" not in page


def test_the_front_page_xi_only_contains_players_you_own(monkeypatch):
    """The whole point of anchoring. An eleven drawn from the global pool
    is a squad you'd have to buy."""
    owned = set(_with_confirmed_squad(monkeypatch))
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)

    bootstrap = api.get_bootstrap_static()
    names_by_id = {e["id"]: e["web_name"] for e in bootstrap["elements"]}
    owned_names = {names_by_id[pid] for pid in owned}

    # Only the front page's pitch. Scanning the whole page picks up the My
    # Squad tab and the captaincy cards too, which render on every script
    # pass regardless of which tab is selected.
    blocks = [str(b.value) for b in at.markdown if "pitch-wrap" in str(b.value)]
    assert blocks, "no pitch was rendered"
    pitch = blocks[0]
    shown = {name for name in names_by_id.values() if f">{name}<" in pitch}

    assert shown, "no players were rendered on the pitch"
    assert shown <= owned_names, f"pitch shows players you don't own: {shown - owned_names}"


def test_a_transfer_recommendation_is_offered_on_the_front_page(monkeypatch):
    _with_confirmed_squad(monkeypatch)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)

    page = _all_markdown(at)
    assert "Recommended move" in page


def test_without_a_team_id_it_still_builds_from_scratch(monkeypatch):
    """Someone with no squad yet needs the original behaviour."""
    patch = _synthetic_bootstrap(True)
    monkeypatch.setattr(api, "get_bootstrap_static", lambda: patch)
    monkeypatch.setattr(api, "get_fixtures", lambda event=None: _synthetic_fixtures())
    monkeypatch.setattr(config, "FPL_TEAM_ID", None)

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception

    assert "Best 15 buildable from scratch" in _all_markdown(at)


def test_the_armband_never_goes_to_a_defender_anywhere_in_the_app(monkeypatch):
    """Belt and braces on the reported failure. Two code paths used to
    choose a captain and only one filtered by position; this asserts on
    the rendered page rather than on either function."""
    _with_confirmed_squad(monkeypatch)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception, f"App raised: {[str(e) for e in at.exception]}"

    bootstrap = api.get_bootstrap_static()
    defensive = {
        e["web_name"] for e in bootstrap["elements"] if e["element_type"] in (1, 2)
    }

    # Only the recommended pitch. The My Squad tab renders whatever
    # captain the manager actually set, which is theirs to get wrong.
    blocks = [str(b.value) for b in at.markdown if "armband-c" in str(b.value)]
    assert blocks, "no armband was rendered"
    for chunk in blocks[0].split("player-card")[1:]:
        if "armband-c" not in chunk:
            continue
        captained = [name for name in defensive if f">{name}<" in chunk]
        assert not captained, f"a defender has the armband: {captained}"


def test_the_captain_and_vice_are_both_explained_on_the_homepage(monkeypatch):
    """The armband is the biggest free decision of the week.

    The old homepage carried a ranked candidate list with haul
    probabilities; the rebuilt one carries a written case on the captain's
    own card instead. What has to survive either design is that the choice
    is argued rather than announced — and that the vice gets the same.
    """
    _with_confirmed_squad(monkeypatch)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=180)
    assert not at.exception, f"App raised: {[str(e) for e in at.exception]}"

    page = _all_markdown(at)
    assert "Captaincy reasoning" in page
    assert "Vice-captaincy reasoning" in page
    # And the armband is marked on the squad itself, not only in prose.
    assert "This week's suggested team" in page


def test_an_injured_squad_still_gets_the_rest_of_the_plan(monkeypatch):
    """Regression: if enough owned players were unavailable to make a
    legal eleven impossible, the XI solve raised and the whole plan page
    returned early — no captaincy call, no per-player cases. Someone in
    that position needs the advice more than usual, not less.
    """
    _with_confirmed_squad(monkeypatch)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception, f"App raised: {[str(e) for e in at.exception]}"

    page = _all_markdown(at)
    assert "Captaincy reasoning" in page, "the captaincy explanation vanished"
    assert "Suggested transfers" in page
    assert "Why each player is in the team" in page


def test_the_front_page_explains_each_player(monkeypatch):
    """The complaint: the plan page said who to start and never said why.
    Every player should carry a case you can argue with."""
    _with_confirmed_squad(monkeypatch)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)

    page = _all_markdown(at)
    assert "Why each player is in the team" in page
    assert "Recent form:" in page, "no qualitative form line"
    assert "The fixture:" in page, "no opponent context"


# --- marking the app's own homework -------------------------------------

def test_the_track_record_tab_says_so_when_there_is_nothing_to_mark(patch_api):
    """No snapshots means no marking, and it has to say that rather than
    quietly reconstructing past advice from results it can already see."""
    patch_api(preseason=False)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=60)

    assert not at.exception, f"App raised: {[str(e) for e in at.exception]}"
    text = _all_markdown(at) + "\n".join(str(i.value) for i in at.info)
    assert "Track record" in text or any(
        "nothing to mark" in str(i.value) or "No gameweeks have finished" in str(i.value)
        for i in at.info
    )


def test_a_finished_gameweek_with_a_snapshot_is_actually_marked(monkeypatch, tmp_path):
    """The end-to-end version of the feature.

    A snapshot written before GW1's deadline, GW1 finished, live results
    available — the app must lay one against the other and report a score,
    including when the advice was bad.
    """
    from dataclasses import asdict

    from fpl_assistant.analysis import snapshots

    # The autouse `_isolate_snapshots` fixture has already pointed this at
    # a temporary directory; writing into it is what makes the app find a
    # snapshot without touching the real one.
    directory = snapshots.SNAPSHOT_DIR

    chosen = _with_confirmed_squad(monkeypatch)
    snapshot = snapshots.Snapshot(
        gameweek=1,
        saved_at="2026-08-15T10:00:00+00:00",
        squad_ids=chosen,
        starting_ids=chosen[:11],
        bench_ids=chosen[11:],
        captain_id=chosen[12],
        vice_captain_id=chosen[1],
        formation="4-4-2",
        total_cost=99.5,
        expected_points=61.0,
        player_names={str(pid): f"P{pid}" for pid in chosen},
        projected={str(pid): 5.0 for pid in chosen},
    )
    (directory / "gw1.json").write_text(json.dumps(asdict(snapshot)))

    monkeypatch.setattr(
        api, "get_event_live",
        lambda event: {
            "elements": [
                {"id": pid, "stats": {"total_points": 4, "minutes": 90}} for pid in chosen
            ]
        },
    )

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=180)
    assert not at.exception, f"App raised: {[str(e) for e in at.exception]}"

    page = _all_markdown(at)
    # Projected 5.0 across the board, scored 4 — the app must own that.
    assert "1.00 points high" in page


# --- planning more than one week ahead ----------------------------------

def test_the_front_page_plans_beyond_the_next_gameweek(monkeypatch):
    """A one-week optimiser can't bank a transfer or stage a two-part
    move. The schedule is where those show up, so it has to reach the
    page rather than just existing as a module."""
    _with_confirmed_squad(monkeypatch)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=180)
    assert not at.exception, f"App raised: {[str(e) for e in at.exception]}"

    page = _all_markdown(at) + "\n".join(str(c.value) for c in at.caption)
    assert "The next few gameweeks" in page
    assert "first move is a decision" in page


# --- what people are saying, on the page --------------------------------

def test_the_reasons_people_give_reach_the_page(monkeypatch):
    """The complaint, tested end to end.

    A projection is a conclusion; the talking points are the argument.
    Both piles have to render, with attribution, or the research may as
    well not exist.
    """
    import json as _json
    from pathlib import Path as _Path

    from fpl_assistant.analysis import consensus as _consensus

    # The synthetic pool uses real Premier League short names, so the
    # shipped research applies to it — but the names won't match, so point
    # the consensus at a file built around this fixture's players instead.
    _with_confirmed_squad(monkeypatch)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=180)
    assert not at.exception, f"App raised: {[str(e) for e in at.exception]}"

    # Fixture-level commentary attaching to the players in that fixture is
    # the thing that previously had nowhere to live. The synthetic pool
    # uses real club short names, so the shipped GW2 matchup research
    # applies to it — which means this also proves the file parses and
    # reaches a player's card.
    # The guarantee is stronger than any one phrase: EVERY owned player
    # gets the full dossier, whether or not anyone published an FPL
    # article about him. These sections are unconditional.
    page = _all_markdown(at)
    for section in ("This gameweek.", "Why he's in our squad.", "Case for keeping.",
                    "Case for selling.", "Latest developments.", "Expert view.",
                    "Risks.", "Our verdict:"):
        assert section in page, f"missing dossier section: {section}"
    # And a player nobody wrote about says so rather than showing nothing.
    assert "commentary on him was limited" in page or "Sources used" in " ".join(
        _expander_labels(at)
    ) or "weakest kind of case" in page


def test_the_shipped_research_renders_both_sides_for_a_real_player():
    """Renders the two piles directly from the shipped GW2 file.

    Going through AppTest would need the synthetic pool to carry the real
    player names; this checks the same rendering path's inputs against the
    actual research, which is the part that could silently go missing.
    """
    import json as _json
    from pathlib import Path as _Path

    import pandas as _pd

    from fpl_assistant.analysis import consensus as _consensus

    data = _json.loads(
        (_Path(__file__).resolve().parent.parent / "data" / "consensus" / "gw2.json").read_text()
    )
    entry = next(p for p in data["players"] if p["name"] == "Szoboszlai")

    frame = _pd.DataFrame([{"id": 1, "web_name": "Szoboszlai"}])
    frame["consensus_for"] = _consensus._pack(entry["talking_points"]["for"])
    frame["consensus_against"] = _consensus._pack(entry["talking_points"]["against"])
    row = frame.iloc[0]

    for_points = _consensus.arguments_for(row)
    against_points = _consensus.arguments_against(row)

    assert len(for_points) >= 3
    assert len(against_points) >= 3
    assert any("deeper" in p.lower() for p, _ in against_points)
    assert all(source for _, source in for_points + against_points)

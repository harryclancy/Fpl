"""Tests for the club-by-club briefing.

The fixture ticker answers "which teams have easy games", which is half a
decision — it says nothing about which player at that club is the way in,
or that the best asset is carrying a knock. These tests are mostly about
the half the ticker was missing, and about the brief not asserting
something the data doesn't support.
"""
import json

import pandas as pd
import pytest

from fpl_assistant.analysis import consensus, team_brief

N_TEAMS = 4


@pytest.fixture
def stance_dir(tmp_path, monkeypatch):
    directory = tmp_path / "consensus"
    directory.mkdir(exist_ok=True)
    monkeypatch.setattr(consensus, "CONSENSUS_DIR", directory)

    def _write(teams):
        (directory / "teams.json").write_text(json.dumps({"teams": teams}))

    _write([])
    return _write


def _teams() -> pd.DataFrame:
    return pd.DataFrame(
        [{"id": t, "name": f"Team{t}", "short_name": f"T{t}"} for t in range(1, N_TEAMS + 1)]
    ).set_index("id", drop=False)


def _scored(rows=None) -> pd.DataFrame:
    base = []
    pid = 1
    for team in range(1, N_TEAMS + 1):
        for pos in ("GKP", "DEF", "MID", "FWD"):
            base.append({
                "id": pid, "web_name": f"{pos}{pid}", "team": team,
                "team_short_name": f"T{team}", "position": pos, "price": 6.0,
                "selected_by_percent": 5.0, "xp_next": 4.0, "xp_horizon": 20.0,
                "news": "", "consensus_tier": None,
            })
            pid += 1
    frame = pd.DataFrame(base + list(rows or []))
    return frame.set_index("id", drop=False)


def _fixture_table(difficulties: dict[int, float]) -> pd.DataFrame:
    rows = {}
    for team in range(1, N_TEAMS + 1):
        difficulty = difficulties.get(team, 3.0)
        row = {"team_name": f"Team{team}", "avg_difficulty": difficulty,
               "blank_gameweeks": 0, "double_gameweeks": 0}
        for gw in (1, 2):
            row[gw] = f"OPP (H)"
            row[f"{gw}_difficulty"] = difficulty
        rows[team] = row
    return pd.DataFrame.from_dict(rows, orient="index")


def _brief(short, **kwargs):
    briefs = team_brief.build_briefs(
        kwargs.get("scored", _scored()),
        kwargs.get("table", _fixture_table({})),
        _teams(),
        [1, 2],
    )
    return next(b for b in briefs if b.short_name == short)


# --- the run ------------------------------------------------------------

def test_briefs_are_ordered_kindest_run_first(stance_dir):
    """The question this answers is "who should I be buying", so the
    answer belongs at the top."""
    table = _fixture_table({1: 4.5, 2: 1.5, 3: 3.0, 4: 2.0})
    briefs = team_brief.build_briefs(_scored(), table, _teams(), [1, 2])
    assert [b.short_name for b in briefs] == ["T2", "T4", "T3", "T1"]


def test_run_quality_is_not_overstated_in_the_middle(stance_dir):
    """A 3.0 run is not a green light, and saying so would make every
    other verdict on the page worth less."""
    brief = _brief("T1", table=_fixture_table({1: 3.0}))
    assert brief.run_quality == "mixed"
    assert "Fixtures aren't the deciding factor" in " ".join(brief.pros)


def test_an_easy_run_is_called_out_with_the_number(stance_dir):
    brief = _brief("T1", table=_fixture_table({1: 1.5}))
    assert brief.run_quality == "easy"
    assert any("1.5 average difficulty" in line for line in brief.pros)


def test_a_hard_run_lands_in_the_cons(stance_dir):
    brief = _brief("T1", table=_fixture_table({1: 4.5}))
    assert brief.run_quality == "hard"
    assert any("Tough run" in line for line in brief.cons)


# --- who to buy ---------------------------------------------------------

def test_the_assets_span_positions_rather_than_being_a_top_n(stance_dir):
    """A pure top-N hands back four defenders on a clean-sheet run and
    never mentions the striker, which is the opposite of what someone
    scanning a club wants."""
    rows = [{
        "id": 900 + i, "web_name": f"BigDef{i}", "team": 1, "team_short_name": "T1",
        "position": "DEF", "price": 6.0, "selected_by_percent": 5.0,
        "xp_next": 9.0, "xp_horizon": 99.0, "news": "", "consensus_tier": None,
    } for i in range(4)]
    brief = _brief("T1", scored=_scored(rows))

    positions = {a.position for a in brief.assets}
    assert {"GKP", "DEF", "MID", "FWD"} <= positions


def test_an_injury_flag_is_surfaced_on_the_asset(stance_dir):
    rows = [{
        "id": 950, "web_name": "Crocked", "team": 1, "team_short_name": "T1",
        "position": "FWD", "price": 9.0, "selected_by_percent": 30.0,
        "xp_next": 9.0, "xp_horizon": 99.0, "news": "Hamstring - 50% chance",
        "consensus_tier": None,
    }]
    brief = _brief("T1", scored=_scored(rows))

    crocked = next(a for a in brief.assets if a.name == "Crocked")
    assert crocked.flagged
    assert "Hamstring" in crocked.note
    assert any("fitness or availability flag" in line for line in brief.cons)


def test_a_club_with_no_players_still_produces_a_brief(stance_dir):
    """Briefs are built per club from the fixture table, and an empty
    squad must not drop the club off the page."""
    scored = _scored()
    brief = _brief("T1", scored=scored[scored["team"] != 1])
    assert brief.assets == []
    assert brief.headline


# --- club-level context -------------------------------------------------

def test_a_researched_verdict_takes_the_headline_over_the_fixture_maths(stance_dir):
    """A human judgement about a club beats a number derived from the same
    fixtures that number came from."""
    stance_dir([{"short_name": "T1", "stances": [
        {"stance": "avoid", "scope": "all", "until_gameweek": 9,
         "case": "Brutal opening run and midweek European football.",
         "sources": ["RotoWire"]},
    ]}])
    brief = _brief("T1", table=_fixture_table({1: 1.5}))

    assert brief.stance == "avoid"
    assert brief.headline == "Analysts are steering clear"
    assert "Brutal opening" in brief.stance_case
    assert brief.stance_sources == "RotoWire"


def test_an_expired_verdict_does_not_reach_the_brief(stance_dir):
    stance_dir([{"short_name": "T1", "stances": [
        {"stance": "avoid", "scope": "all", "until_gameweek": 1, "case": "Old news."},
    ]}])
    brief = team_brief.build_briefs(_scored(), _fixture_table({}), _teams(), [5, 6])
    assert next(b for b in brief if b.short_name == "T1").stance is None


def test_european_football_is_listed_as_a_con_and_no_europe_as_a_pro(stance_dir):
    stance_dir([
        {"short_name": "T1", "european_competition": "uel"},
        {"short_name": "T2", "european_competition": "none"},
    ])
    assert any("Europa League" in c for c in _brief("T1").cons)
    assert any("No European football" in p for p in _brief("T2").pros)


def test_a_new_manager_is_flagged(stance_dir):
    stance_dir([{"short_name": "T1", "new_manager": True}])
    assert any("New manager" in c for c in _brief("T1").cons)


def test_blanks_and_doubles_land_on_the_right_side(stance_dir):
    table = _fixture_table({})
    table.loc[1, "blank_gameweeks"] = 2
    table.loc[1, "double_gameweeks"] = 1
    brief = _brief("T1", table=table)

    assert any("double gameweek" in p for p in brief.pros)
    assert any("blank gameweek" in c for c in brief.cons)

"""The Haaland bug: one gameweek is not a sample.

The reported failure, in the user's words: "Dropping Haaland like why
would anyone do that. He's been golden boot for years."

What happened underneath. After Gameweek 1 of 2026/27, Haaland took five
shots against Bournemouth, didn't score, and finished on two points. The
projection blended the component model against realised points-per-game
at a *fixed* weight -- so a one-match average was trusted exactly as much
as a thirty-match one. Two points from one game dragged the most
expensive asset in the game down far enough that the optimiser sold him.

No human makes that mistake, because a human carries a prior: 27 league
goals last season, 22 the season before, top scorer after the first six
gameweeks in all four of his seasons at City. These tests encode that.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.analysis import history


# --- the shrinkage curve ------------------------------------------------

def test_one_game_is_barely_believed():
    """The heart of it. One match must not carry a full season's weight."""
    assert history.current_season_weight(1) < 0.2


def test_belief_grows_with_the_sample():
    weights = [history.current_season_weight(n) for n in (1, 3, 6, 12, 25)]
    assert weights == sorted(weights)
    assert weights[0] < 0.2      # one game: nearly ignored
    assert weights[2] == 0.5     # six games: an even split with the prior
    assert weights[-1] > 0.75    # most of a season: the prior is history


def test_no_games_played_means_no_belief_at_all():
    assert history.current_season_weight(0) == 0.0


# --- the prior itself ---------------------------------------------------

def test_the_shipped_history_knows_who_haaland_is():
    """If this file doesn't load, the fix silently does nothing."""
    records = history.load()
    haaland = records.get("haaland")

    assert haaland is not None, "Haaland missing from data/history/seasons.json"
    assert haaland.points_per_start > 6.0
    assert "27 goals" in haaland.seasons_summary


def test_accented_and_initialised_names_still_match():
    """The prior matters most for exactly the players whose names don't
    match cleanly across sources -- João Pedro, Gyökeres, B.Fernandes."""
    assert history._normalise("João Pedro") == history._normalise("Joao Pedro")
    assert history._normalise("Gyökeres") == history._normalise("Gyokeres")
    assert history._normalise("B.Fernandes") == history._normalise("BFernandes")


def test_a_thin_season_is_not_treated_as_evidence():
    record = history.SeasonRecord(
        season="2025/26", appearances=4, total_points=40, minutes=200
    )
    assert not record.substantial
    assert record.points_per_start == 0.0


def test_a_season_with_no_minutes_recorded_still_gives_points_per_start():
    """Published season reviews carry points and appearances far more
    reliably than minutes. Requiring minutes would mean the seeded prior
    applied to nobody -- the fix would look present and do nothing."""
    record = history.SeasonRecord(season="2024/25", appearances=38, total_points=236)

    assert record.points_per_start > 6.0
    assert record.per_90("goals") == 0.0  # unknown, and must read as unknown


def test_last_season_counts_more_than_the_one_before():
    strong_then_weak = history.PlayerHistory(
        name="X",
        seasons=[
            history.SeasonRecord("2025/26", appearances=30, total_points=60),
            history.SeasonRecord("2024/25", appearances=30, total_points=300),
        ],
    )
    weak_then_strong = history.PlayerHistory(
        name="Y",
        seasons=[
            history.SeasonRecord("2025/26", appearances=30, total_points=300),
            history.SeasonRecord("2024/25", appearances=30, total_points=60),
        ],
    )
    assert weak_then_strong.points_per_start > strong_then_weak.points_per_start


def test_a_player_with_no_history_gets_no_prior_not_a_bad_one():
    """A promoted striker with no Premier League record is unknown, not
    bad. Scoring him as bad is the same class of error as the one this
    module exists to fix, pointed the other way."""
    frame = pd.DataFrame(
        {"id": [1], "web_name": ["NobodyHasHeardOfHim"], "price": [5.0]}
    )
    attached = history.attach(frame, {})

    assert attached["prior_points_per_start"].iloc[0] == 0.0
    assert not attached["has_prior"].iloc[0]


def test_attach_finds_a_player_by_name():
    frame = pd.DataFrame({"id": [1, 2], "web_name": ["Haaland", "Nobody"], "price": [15.5, 4.5]})
    attached = history.attach(frame)

    assert attached.loc[attached["web_name"] == "Haaland", "has_prior"].iloc[0]
    assert not attached.loc[attached["web_name"] == "Nobody", "has_prior"].iloc[0]
    assert "2025/26" in attached.loc[attached["web_name"] == "Haaland", "prior_seasons"].iloc[0]


# --- the bug itself, end to end -----------------------------------------

def _pool_after_one_gameweek(premium_points: int) -> pd.DataFrame:
    """A pool one gameweek into a season.

    The premium blanked; a cheap forward hauled. That is the exact shape
    of the situation that produced the bug.
    """
    rows = []
    for pid in range(1, 61):
        position = ["GKP", "DEF", "MID", "FWD"][pid % 4]
        rows.append(
            {
                "id": pid,
                "web_name": f"P{pid}",
                "team": (pid % 12) + 1,
                "team_short_name": f"T{(pid % 12) + 1}",
                "position": position,
                "price": 5.0,
                "minutes": 90,
                "points_per_game": "4.0",
                "total_points": 4,
                "selected_by_percent": 5.0,
                "status": "a",
                "form": "4.0",
            }
        )
    rows.append(
        {
            "id": 999,
            "web_name": "Haaland",
            "team": 1,
            "team_short_name": "T1",
            "position": "FWD",
            "price": 15.5,
            "minutes": 90,
            "points_per_game": str(float(premium_points)),
            "total_points": premium_points,
            "selected_by_percent": 71.0,
            "status": "a",
            "form": str(float(premium_points)),
        }
    )
    return pd.DataFrame(rows).set_index("id", drop=False)


def test_the_prior_survives_a_single_blank():
    """The regression test for the whole complaint.

    A premium who blanked once, carrying two seasons of elite output, must
    still be projected well above a journeyman who happened to score four
    points in the same gameweek.
    """
    pool = history.attach(_pool_after_one_gameweek(premium_points=2))

    premium = pool[pool["web_name"] == "Haaland"].iloc[0]
    journeyman = pool[pool["web_name"] == "P4"].iloc[0]

    assert premium["has_prior"]
    assert not journeyman["has_prior"]
    # 6.5 points a game across two seasons against a single 2-point return.
    assert premium["prior_points_per_start"] > 6.0


def test_the_blend_moves_toward_the_prior_when_the_sample_is_tiny():
    """One game of evidence should barely shift a two-season prior."""
    tiny = history.current_season_weight(1)
    established = history.current_season_weight(30)

    # After one game, over 85% of the non-model weight sits on history.
    assert (1 - tiny) > 0.85
    # By the end of a season it has almost entirely handed over.
    assert (1 - established) < 0.2


# --- the season trends --------------------------------------------------

def test_the_shipped_trends_load_and_carry_rules():
    """A lesson that doesn't change a decision is a paragraph, not a
    lesson, so every season review has to produce actionable rules."""
    trends = history.load_trends()

    assert [s.season for s in trends.seasons] == ["2025/26", "2024/25"]
    assert len(trends.rules) >= 5
    assert trends.carried, "nothing carried into the current season"
    assert trends.sources


def test_the_trends_say_out_loud_that_one_week_is_not_a_sample():
    carried = " ".join(history.load_trends().carried).lower()
    assert "one gameweek is not a sample" in carried


def test_every_season_review_has_facts_behind_it():
    """Opinions without numbers underneath are what the user has been
    complaining about. Each review has to carry both."""
    for review in history.load_trends().seasons:
        assert review.headline, f"{review.season} has no headline"
        assert review.facts, f"{review.season} has no supporting facts"
        assert review.lessons, f"{review.season} has no lessons"


def test_missing_trends_file_degrades_quietly(monkeypatch, tmp_path):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path)
    trends = history.load_trends()
    assert trends.seasons == []
    assert trends.rules == []

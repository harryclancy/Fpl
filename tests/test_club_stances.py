"""Do club-level expert verdicts actually reach the optimiser?

This file exists because of a specific, embarrassing failure. Analysts
were unanimous that Bournemouth assets should be avoided until their
fixture run cleared, that advice was written into the app's research
data, the app displayed it -- and the recommended squad kept containing
Bournemouth defenders. The verdict had been stored as prose inside one
player's write-up, so it applied to that one player. Every other player at
the club was invisible to it, and cheap defenders at a club with a brutal
run are exactly what an optimiser reaches for, because it can see the
price and not the reason for the price.

The lesson generalises past Bournemouth: advice about a club has to be
stored as data about the club. So these tests assert on the mechanism, not
on the current contents of the research file -- they build their own
stances and check the squad changes.
"""
import json

import pandas as pd
import pytest

from fpl_assistant.analysis import consensus, squad_builder


@pytest.fixture
def team_file(tmp_path, monkeypatch):
    def _write(teams):
        directory = tmp_path / "consensus"
        directory.mkdir(exist_ok=True)
        (directory / "teams.json").write_text(json.dumps({"teams": teams}))
        monkeypatch.setattr(consensus, "CONSENSUS_DIR", directory)
        return consensus.load_team_context()

    return _write


def _players(rows) -> pd.DataFrame:
    return pd.DataFrame(rows).set_index("id", drop=False)


AVOID_CLUB = {
    "short_name": "BOU",
    "stances": [{"stance": "avoid", "scope": "all", "until_gameweek": 9,
                 "case": "Worst opening run in the league."}],
}


# --- the mechanism ------------------------------------------------------

def test_club_verdict_reaches_players_no_analyst_named(team_file):
    """The whole point. The advice names the club; the penalty has to land
    on the squad player nobody wrote an article about."""
    context = team_file([AVOID_CLUB])
    players = _players([
        {"id": 1, "web_name": "SomeoneNobodyWroteAbout", "team_short_name": "BOU", "position": "DEF"},
        {"id": 2, "web_name": "Neutral", "team_short_name": "CHE", "position": "DEF"},
    ])

    out = consensus.annotate_clubs(players, context, from_event=1, horizon=5)

    assert out.loc[1, "club_stance"] == "avoid"
    assert out.loc[1, "club_stance_bonus"] < 0
    assert out.loc[2, "club_stance_bonus"] == 0.0


def test_scope_limits_a_verdict_to_the_positions_it_was_about(team_file):
    context = team_file([{
        "short_name": "COV",
        "stances": [{"stance": "avoid", "scope": ["GKP", "DEF"], "until_gameweek": 6,
                     "case": "Promoted defence, brutal opening."}],
    }])
    players = _players([
        {"id": 1, "web_name": "Keeper", "team_short_name": "COV", "position": "GKP"},
        {"id": 2, "web_name": "Defender", "team_short_name": "COV", "position": "DEF"},
        {"id": 3, "web_name": "Winger", "team_short_name": "COV", "position": "MID"},
    ])

    out = consensus.annotate_clubs(players, context, from_event=1, horizon=5)

    assert out.loc[1, "club_stance"] == "avoid"
    assert out.loc[2, "club_stance"] == "avoid"
    # The advice was about picking promoted centre-backs, not about the winger.
    assert out.loc[3, "club_stance"] is None


def test_the_stronger_of_two_overlapping_verdicts_wins(team_file):
    """A club can carry an avoid for defenders and a milder caution for
    attackers. Neither should clobber the other."""
    context = team_file([{
        "short_name": "COV",
        "stances": [
            {"stance": "avoid", "scope": ["DEF"], "until_gameweek": 6, "case": "x"},
            {"stance": "caution", "scope": ["DEF", "MID"], "until_gameweek": 6, "case": "y"},
        ],
    }])
    players = _players([
        {"id": 1, "web_name": "D", "team_short_name": "COV", "position": "DEF"},
        {"id": 2, "web_name": "M", "team_short_name": "COV", "position": "MID"},
    ])

    out = consensus.annotate_clubs(players, context, from_event=1, horizon=5)
    assert out.loc[1, "club_stance"] == "avoid"
    assert out.loc[2, "club_stance"] == "caution"


# --- expiry -------------------------------------------------------------
# A fixture-run warning written in August must not still be penalising the
# club at Christmas. Research data that can't expire silently rots.

def test_a_verdict_fades_as_the_window_it_covers_passes(team_file):
    context = team_file([AVOID_CLUB])
    players = _players([{"id": 1, "web_name": "X", "team_short_name": "BOU", "position": "DEF"}])

    early = consensus.annotate_clubs(players, context, 1, 5).loc[1, "club_stance_bonus"]
    late = consensus.annotate_clubs(players, context, 7, 5).loc[1, "club_stance_bonus"]

    assert early < late < 0, "the penalty should shrink as the bad run runs out"


def test_a_verdict_expires_completely_once_its_window_has_passed(team_file):
    context = team_file([AVOID_CLUB])
    players = _players([{"id": 1, "web_name": "X", "team_short_name": "BOU", "position": "DEF"}])

    out = consensus.annotate_clubs(players, context, from_event=9, horizon=5)
    assert out.loc[1, "club_stance_bonus"] == 0.0
    assert out.loc[1, "club_stance"] is None


def test_a_verdict_with_no_expiry_always_applies(team_file):
    context = team_file([{"short_name": "BOU",
                          "stances": [{"stance": "avoid", "scope": "all", "case": "c"}]}])
    players = _players([{"id": 1, "web_name": "X", "team_short_name": "BOU", "position": "DEF"}])
    assert consensus.annotate_clubs(players, context, 30, 5).loc[1, "club_stance_bonus"] < 0


# --- robustness ---------------------------------------------------------

def test_missing_team_context_is_harmless():
    players = _players([{"id": 1, "web_name": "X", "team_short_name": "BOU", "position": "DEF"}])
    out = consensus.annotate_clubs(players, {}, 1, 5)
    assert out.loc[1, "club_stance_bonus"] == 0.0


def test_a_club_absent_from_the_file_gets_neutral_treatment(team_file):
    """teams.json is a lookup, not a claim about who is in the league.
    Getting the promoted/relegated set wrong must cost nothing."""
    context = team_file([AVOID_CLUB])
    players = _players([{"id": 1, "web_name": "X", "team_short_name": "ZZZ", "position": "DEF"}])
    assert consensus.annotate_clubs(players, context, 1, 5).loc[1, "club_stance_bonus"] == 0.0


def test_an_unrecognised_stance_label_is_ignored_not_guessed(team_file):
    context = team_file([{"short_name": "BOU",
                          "stances": [{"stance": "extremely-bad", "scope": "all"}]}])
    players = _players([{"id": 1, "web_name": "X", "team_short_name": "BOU", "position": "DEF"}])
    assert consensus.annotate_clubs(players, context, 1, 5).loc[1, "club_stance_bonus"] == 0.0

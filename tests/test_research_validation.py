"""The rules that decide whether researched data is allowed to land.

These matter more now that the research is written by an automated agent
than they did when it was hand-entered. A human writing this file gets
bored and leaves a field blank; an agent writes something plausible for
every field, every time, and plausible-but-unsupported is the failure mode
that actually reaches users. So the rules are about evidence and
attribution rather than completeness.

Each test states the failure it prevents.
"""
import pytest

from fpl_assistant.research import validation

GOOD_PLAYER = {
    "name": "B.Fernandes",
    "full_name": "Bruno Fernandes",
    "tier": "strong",
    "verdict": "The safest premium midfielder.",
    "case": "Penalties, set pieces and the volume of a nailed-on starter.",
    "watch_out": "He missed another penalty in pre-season.",
    "key_stats": ["9 goals and 24 assists last season", "On penalties and corners"],
    "voices": [{"source": "Fantasy Football Scout", "take": "Flagged the pre-season penalty misses as a real concern."}],
    "sources": ["Fantasy Football Scout"],
}


def _file(**overrides):
    data = {"gameweek": 1, "researched": "2026-08-19", "players": [dict(GOOD_PLAYER)]}
    data.update(overrides)
    return data


def _with(**player_overrides):
    player = dict(GOOD_PLAYER)
    player.update(player_overrides)
    return _file(players=[player])


def _has(problems, fragment):
    return any(fragment in problem for problem in problems)


# --- a clean file passes ------------------------------------------------

def test_a_complete_entry_is_accepted():
    assert validation.validate_players(_file()) == []


# --- evidence -----------------------------------------------------------

def test_an_entry_with_no_counter_argument_is_rejected():
    """A recommendation you can't argue against isn't advice — and an
    agent will happily write a page of praise with no risks in it."""
    problems = validation.validate_players(_with(watch_out=""))
    assert _has(problems, "no counter-argument")


def test_an_entry_with_too_few_numbers_is_rejected():
    problems = validation.validate_players(_with(key_stats=["one fact"]))
    assert _has(problems, "fewer than 2 supporting numbers")


def test_an_unattributed_take_is_rejected():
    """"Analysts say" is not a source, and is exactly how an unchecked
    claim survives."""
    problems = validation.validate_players(
        _with(voices=[{"take": "Everyone likes him a lot this week honestly."}])
    )
    assert _has(problems, "unattributed take")


def test_a_thin_take_is_rejected():
    problems = validation.validate_players(
        _with(voices=[{"source": "RotoWire", "take": "Good."}])
    )
    assert _has(problems, "too thin to be informative")


def test_an_entry_with_no_voices_at_all_is_rejected():
    problems = validation.validate_players(_with(voices=[]))
    assert _has(problems, "records no attributed takes")


# --- structure ----------------------------------------------------------

def test_an_unknown_tier_is_rejected_rather_than_ignored():
    """annotate() skips tiers it doesn't recognise, so this would fail
    silently and the player would simply never be weighted."""
    problems = validation.validate_players(_with(tier="quite_good"))
    assert _has(problems, "is not one of")


def test_a_duplicate_player_is_rejected():
    data = _file()
    data["players"] = [dict(GOOD_PLAYER), dict(GOOD_PLAYER)]
    assert _has(validation.validate_players(data), "appears twice")


def test_a_missing_research_date_is_rejected():
    """Every claim in these files has a shelf life measured in days."""
    assert _has(validation.validate_players(_file(researched="")), "researched")


def test_an_empty_file_is_rejected():
    assert validation.validate_players({"players": []}) == ["the file contains no player entries"]


# --- disagreement -------------------------------------------------------

def test_a_dissent_without_sources_is_rejected():
    problems = validation.validate_players(
        _with(dissent={"case": "Several analysts think the price is wrong.", "sources": []})
    )
    assert _has(problems, "dissent cites no sources")


def test_a_contested_player_cannot_also_be_a_hard_lock():
    """The must-have lock forces a player into the squad. Applying it to
    someone the file itself records an argument about is the app
    contradicting its own evidence."""
    problems = validation.validate_players(
        _with(tier="must_have",
              dissent={"case": "Two outlets say avoid him entirely.", "sources": ["RotoWire"]})
    )
    assert _has(problems, "near-unanimity")


# --- the club-wide prose trap ------------------------------------------

def test_club_wide_advice_in_a_players_prose_is_rejected():
    """The original bug: "avoid Bournemouth assets" written into one
    player's write-up reached one player, and the optimiser went on
    picking the club's other twenty."""
    problems = validation.validate_players(
        _with(watch_out="Analysts are saying avoid Bournemouth assets entirely for now."),
        team_context={},
    )
    assert _has(problems, "reaches only")


def test_the_same_prose_is_fine_when_the_club_carries_a_stance():
    problems = validation.validate_players(
        _with(watch_out="Analysts are saying avoid Bournemouth assets entirely for now."),
        team_context={"BOU": {"stances": [{"stance": "avoid"}]}},
    )
    assert not _has(problems, "reaches only")


# --- club stances -------------------------------------------------------

def _team_file(**stance_overrides):
    stance = {
        "stance": "avoid", "scope": "all", "until_gameweek": 9,
        "case": "Bournemouth have the toughest opening run in the division by some distance.",
        "sources": ["RotoWire"],
    }
    stance.update(stance_overrides)
    return {"teams": [{"short_name": "BOU", "stances": [stance]}]}


def test_a_good_stance_is_accepted():
    assert validation.validate_teams(_team_file()) == []


def test_a_stance_with_no_expiry_is_rejected():
    """Fixture-run advice written in August must not still be penalising
    a club in May."""
    problems = validation.validate_teams(_team_file(until_gameweek=None))
    assert _has(problems, "still be applied in May")


def test_a_stance_with_no_sources_is_rejected():
    assert _has(validation.validate_teams(_team_file(sources=[])), "cites no sources")


def test_a_thin_stance_is_rejected():
    assert _has(validation.validate_teams(_team_file(case="Bad run.")), "too thin")


def test_an_unrecognised_stance_label_is_rejected():
    problems = validation.validate_teams(_team_file(stance="quite-bad"))
    assert _has(problems, "ignored silently")


def test_a_duplicate_club_is_rejected():
    data = _team_file()
    data["teams"] = data["teams"] * 2
    assert _has(validation.validate_teams(data), "shadow each other")


# --- odds ---------------------------------------------------------------

def _odds_file(players=None):
    return {
        "gameweek": 1, "researched": "2026-08-19",
        "players": players if players is not None else [
            {"name": "Haaland", "anytime_goalscorer": 1.44, "captain_share": 62},
        ],
        "matchups": [],
    }


def test_good_odds_are_accepted():
    assert validation.validate_odds(_odds_file()) == []


def test_an_implausible_price_is_rejected():
    """Decimal odds are always above 1. A 0.8 means someone has written a
    probability into a price field, and it would read as an 80% shot."""
    problems = validation.validate_odds(
        _odds_file([{"name": "X", "anytime_goalscorer": 0.8}])
    )
    assert _has(problems, "not a plausible decimal price")


def test_captain_shares_that_exceed_the_field_are_rejected():
    """Every manager has one armband. Shares totalling 200% would make
    effective ownership — and therefore every rank calculation — nonsense.
    """
    problems = validation.validate_odds(_odds_file([
        {"name": "A", "captain_share": 70},
        {"name": "B", "captain_share": 65},
    ]))
    assert _has(problems, "more than the field can spend")


def test_a_share_outside_a_percentage_is_rejected():
    problems = validation.validate_odds(_odds_file([{"name": "A", "captain_share": 140}]))
    assert _has(problems, "not a percentage")


def test_odds_without_a_date_are_rejected():
    """Odds go stale within days — faster than anything else in here."""
    data = _odds_file()
    data["researched"] = ""
    assert _has(validation.validate_odds(data), "stale within days")

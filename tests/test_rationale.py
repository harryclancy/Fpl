"""Tests for report-to-player cross-referencing in rationale.py.

FPL's compact `web_name` (often just a surname, sometimes styled
"B.Fernandes") frequently won't literally match how a report written in
prose refers to a player ("Bruno Fernandes"). This locks in that the
match falls back to first+second name too.
"""
import pandas as pd

from fpl_assistant.analysis import rationale
from fpl_assistant.analysis.rationale import _report_mention, captain_rationale, player_rationale

REPORT_TEXT = """
## Player notes

- **Bruno Fernandes** (Man Utd) — best fixture swing of any side, back-to-back promoted sides.
- **Havertz** — the headline GW1 differential pick, sub-7% ownership.
"""


def _row(**overrides):
    base = {
        "id": 1, "code": 100, "web_name": "B.Fernandes", "first_name": "Bruno",
        "second_name": "Fernandes", "team": 1, "team_short_name": "MUN", "position": "MID",
        "price": 9.0, "selected_by_percent": 20.0, "scoring_basis": "preseason",
        "fixture_run_difficulty": 2.5, "chance_of_playing_next_round": 100, "news": "",
        "transfers_in_event": 0, "transfers_out_event": 0,
    }
    base.update(overrides)
    return pd.Series(base)


def test_report_mention_matches_full_name_not_just_web_name():
    row = _row()
    mention = _report_mention(row, REPORT_TEXT)
    assert mention is not None
    assert "fixture swing" in mention


def test_report_mention_falls_back_to_surname_only():
    row = _row(web_name="Havertz", first_name="Kai", second_name="Havertz")
    mention = _report_mention(row, REPORT_TEXT)
    assert mention is not None
    assert "differential" in mention


def test_report_mention_none_when_no_match():
    row = _row(web_name="Nobody", first_name="No", second_name="Body")
    assert _report_mention(row, REPORT_TEXT) is None


def test_player_rationale_surfaces_mention_prominently():
    row = _row()
    text = player_rationale(row, REPORT_TEXT)
    assert "What managers are saying" in text
    assert "fixture swing" in text


def test_player_rationale_leads_with_the_argument_not_a_stat_dump():
    """The writeup should read as a case for the pick. Numbers belong on
    one supporting line at the end, not stacked up front -- an earlier
    version opened with a projection, form, xGI, average FDR, minutes
    percentage and transfer momentum before saying anything a manager
    could act on."""
    row = _row()
    text = player_rationale(row, REPORT_TEXT)

    first_paragraph = text.split("\n\n")[0]
    assert "pts projected" not in first_paragraph
    assert "avg FDR" not in first_paragraph

    # Retired clutter should be gone entirely.
    assert "ICT index" not in text
    assert "net transfers" not in text
    assert "No specific community/analyst commentary" not in text


def test_captain_rationale_checks_both_captain_and_vice():
    captain = _row()
    vice = _row(id=2, web_name="Havertz", first_name="Kai", second_name="Havertz", code=101)
    text = captain_rationale(captain, vice, REPORT_TEXT)
    assert "fixture swing" in text
    assert "differential" in text


# --- the qualitative case -----------------------------------------------
# The complaint: "I need to know why you're picking them qualitatively.
# Eg Pedro scored last week and next opponent are weak according to many
# sources." Those two sentences are what a manager actually says out loud,
# and both were either missing or compressed into a stats line.

def _story_row(**overrides) -> pd.Series:
    base = {
        "web_name": "Pedro", "team_short_name": "CHE", "position": "FWD", "price": 7.5,
        "event_points": 8, "form": 6.2, "fixture_run_difficulty": 2.1,
        "selected_by_percent": 48.0, "status": "a", "news": "", "minutes": 900,
        "xp_next": 5.1, "xp_horizon": 24.0, "points_per_game": 5.0, "bonus": 6,
        "ict_index": 120.0, "expected_goal_involvements": 6.2,
        "consensus_verdict": None, "consensus_reason": None, "consensus_watch_out": None,
    }
    base.update(overrides)
    return pd.Series(base)


def test_a_haul_last_week_is_stated_as_a_haul():
    assert "Hauled last week" in rationale.form_story(_story_row(event_points=13))


def test_a_return_last_week_is_stated_plainly():
    story = rationale.form_story(_story_row(event_points=8))
    assert "Returned last week (8 points)" in story


def test_a_blank_last_week_is_not_dressed_up():
    """A write-up that only ever sounds positive is useless."""
    assert "didn't score last week" in rationale.form_story(
        _story_row(event_points=0, form=1.5)
    ).lower()


def test_a_quiet_run_is_admitted():
    assert "the wider run is quiet" in rationale.form_story(_story_row(event_points=1, form=1.2))


def test_form_reads_as_words_not_as_a_bare_number():
    story = rationale.form_story(_story_row())
    assert "form" in story.lower()
    # It must say what happened, not just print a metric.
    assert "last week" in story


def test_no_recent_data_produces_no_form_claim():
    """Preseason. Inventing a form story from nothing is worse than
    staying quiet."""
    assert rationale.form_story(_story_row(event_points=None, form=0)) is None


# --- the fixture --------------------------------------------------------

def test_the_fixture_names_the_opponent():
    line = rationale.opponent_story(_story_row(), opponent="FUL (H)")
    assert "FUL (H)" in line


def test_an_easy_fixture_is_called_easy():
    line = rationale.opponent_story(_story_row(fixture_run_difficulty=2.0), opponent="COV (H)")
    assert "about as kind as this gets" in line


def test_a_hard_fixture_is_called_hard():
    line = rationale.opponent_story(_story_row(fixture_run_difficulty=4.6), opponent="MCI (A)")
    assert "hardest fixtures on the board" in line


def test_a_neutral_fixture_is_not_spun_either_way():
    """The failure mode of these write-ups is that everything sounds like
    a reason to buy."""
    line = rationale.opponent_story(_story_row(fixture_run_difficulty=3.1), opponent="EVE (A)")
    assert "not a reason to pick him or to drop him" in line


def test_the_market_view_is_included_when_priced():
    line = rationale.opponent_story(_story_row(p_goal_odds=0.455), opponent="FUL (H)")
    assert "46% to score" in line
    assert "market's read on this specific fixture" in line


def test_a_researched_matchup_note_is_surfaced():
    """What typically happens when these two meet — the thing a per-90
    rate cannot express."""
    line = rationale.opponent_story(
        _story_row(team_short_name="MCI"), opponent="BOU", gameweek=1,
    )
    assert "last four" in line


def test_no_fixture_information_produces_no_fixture_claim():
    assert rationale.opponent_story(_story_row(fixture_run_difficulty=None), opponent=None) is None


# --- assembled ----------------------------------------------------------

def test_the_full_write_up_leads_with_form_and_fixture():
    text = rationale.player_rationale(_story_row(opponent="FUL (H)", _gameweek=1))
    assert "Recent form:" in text
    assert "The fixture:" in text
    assert text.index("Recent form:") < text.index("The fixture:")


def test_the_write_up_leads_with_full_seasons_before_last_saturday():
    """The user's complaint, in the write-up rather than the model.

    Two gameweeks in, "27 goals last season" is better evidence than
    "blanked on Saturday", and a case that opens with the blank is
    leading with the least informative thing it knows.
    """
    row = pd.Series(
        {
            "web_name": "Haaland",
            "team_short_name": "MCI",
            "price": 15.5,
            "prior_seasons": "2025/26: 27 goals, 8 assists in 35 games (239 pts)",
            "event_points": 2,
            "form": 2.0,
        }
    )
    text = rationale.player_rationale(row)

    assert "Over full seasons" in text
    assert "27 goals" in text


def test_a_player_with_no_prior_seasons_is_written_up_without_one():
    row = pd.Series({"web_name": "Newboy", "team_short_name": "HUL", "price": 4.5})
    assert rationale.track_record_story(row) == ""
    assert "Over full seasons" not in rationale.player_rationale(row)


def test_the_write_up_leads_with_the_argument_not_the_number():
    """What people said comes before what the model computed.

    A projection is a conclusion — a manager can only accept or reject it.
    "He's been playing deeper in a double pivot" is reasoning they can
    weigh, and it is what they asked for.
    """
    from fpl_assistant.analysis import consensus

    frame = pd.DataFrame([{"web_name": "Szoboszlai", "team_short_name": "LIV", "price": 7.0}])
    frame["consensus_for"] = consensus._pack(
        [{"point": "He is on penalties, corners and free-kicks", "source": "RotoWire"}]
    )
    frame["consensus_against"] = consensus._pack(
        [{"point": "He has been playing deeper in a double pivot", "source": "Scout"}]
    )
    text = rationale.player_rationale(frame.iloc[0])

    assert "Why people like him" in text
    assert "penalties" in text
    assert "The worry" in text
    assert "deeper" in text
    assert "RotoWire" in text and "Scout" in text


def test_a_player_nobody_has_written_about_gets_no_argument_line():
    row = pd.Series({"web_name": "Anon", "team_short_name": "HUL", "price": 4.5})
    assert rationale.headline_argument(row) == ""
    assert "Why people like him" not in rationale.player_rationale(row)

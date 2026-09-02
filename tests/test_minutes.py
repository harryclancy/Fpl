"""Expected minutes from the selection record, not from press conferences.

The flaw: minutes counted as "assessed" only when a retrieved article
discussed a player's selection. Three days before a deadline nothing does,
so all fifteen came back UNASSESSED, every one took the same penalty, and
the sell-urgency ranking carried no information at all.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.analysis import minutes


def test_an_ever_present_is_very_secure_without_anyone_writing_about_him():
    """A team sheet is evidence. Someone who has started every game and
    played every minute has said more about his expected minutes than a
    press conference ever will."""
    got = minutes.assess(starts=8, appearances=8, minutes=720, team_games=8)
    assert got.category == minutes.VERY_SECURE
    assert got.assessed
    assert got.confidence == 1.0


def test_a_regular_starter_is_secure():
    got = minutes.assess(starts=6, appearances=7, minutes=520, team_games=8)
    assert got.category == minutes.SECURE


def test_a_rotation_player_is_a_concern():
    got = minutes.assess(starts=3, appearances=7, minutes=300, team_games=8)
    assert got.category in (minutes.SLIGHT, minutes.SIGNIFICANT)


def test_a_substitute_is_a_significant_concern():
    got = minutes.assess(starts=1, appearances=6, minutes=110, team_games=8)
    assert got.category == minutes.SIGNIFICANT


def test_a_player_with_no_record_and_no_news_stays_unassessed():
    """UNASSESSED now means what it says — a new signing or someone who
    has not featured — rather than "nobody wrote an article"."""
    got = minutes.assess(starts=0, appearances=0, minutes=0, team_games=8)
    assert got.category == minutes.UNASSESSED
    assert not got.assessed


def test_early_season_holds_back_from_asserting_either_way():
    got = minutes.assess(starts=1, appearances=1, minutes=90, team_games=1)
    assert got.category == minutes.SLIGHT
    assert "too little record" in got.reasons[0]


# --- news modifies the base, it does not replace it ----------------------

def test_a_knock_downgrades_a_secure_starter_rather_than_erasing_him():
    """The worked example from the brief: BASE secure, press conference
    says he has a knock, result is a significant concern."""
    base = minutes.assess(starts=8, appearances=8, minutes=720, team_games=8)
    after = minutes.assess(starts=8, appearances=8, minutes=720, team_games=8,
                           injury_talk=True)
    assert base.category == minutes.VERY_SECURE
    assert after.category == minutes.SECURE
    assert "injury reported" in after.modifiers[0]


def test_news_can_only_move_a_player_down_the_ladder():
    """An article saying somebody trained is not the same as being picked,
    so positive news may confirm security but never manufacture it."""
    fringe = minutes.assess(starts=1, appearances=6, minutes=110, team_games=8,
                            positive_team_news=True)
    assert fringe.category == minutes.SIGNIFICANT


def test_positive_team_news_confirms_an_already_secure_base():
    got = minutes.assess(starts=8, appearances=8, minutes=720, team_games=8,
                         positive_team_news=True)
    assert got.category == minutes.VERY_SECURE
    assert any("confirms" in m for m in got.modifiers)


def test_a_suspension_ends_the_question():
    got = minutes.assess(starts=8, appearances=8, minutes=720, team_games=8,
                         suspension=True)
    assert got.category == minutes.MAJOR_DOUBT


def test_the_official_chance_of_playing_dominates():
    got = minutes.assess(starts=8, appearances=8, minutes=720, team_games=8,
                         chance_of_playing=25)
    assert got.category == minutes.MAJOR_DOUBT


def test_modifiers_stack():
    got = minutes.assess(starts=8, appearances=8, minutes=720, team_games=8,
                         injury_talk=True, omission_talk=True, rotation_talk=True)
    assert got.category in (minutes.SIGNIFICANT, minutes.MAJOR_DOUBT)
    assert len(got.modifiers) == 3


def test_confidence_falls_with_the_category():
    ladder = [minutes.CONFIDENCE[c] for c in minutes.LADDER]
    assert ladder == sorted(ladder, reverse=True), "confidence must fall down the ladder"


def test_the_engine_reads_the_graded_category_not_a_binary_flag():
    """The specific regression: every player taking the same penalty."""
    from fpl_assistant.analysis import squad_decision as sd

    def owned(category):
        return sd.PlayerSignals(name="X", club="MCI", position="MID", price=7.0,
                                minutes_category=category)

    secure = sd.assess(owned(minutes.VERY_SECURE)).sell_urgency
    doubtful = sd.assess(owned(minutes.MAJOR_DOUBT)).sell_urgency
    unassessed = sd.assess(owned(minutes.UNASSESSED)).sell_urgency
    assert doubtful > unassessed > secure, (secure, unassessed, doubtful)

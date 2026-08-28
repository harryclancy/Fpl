"""The three-section homepage, and the reasoning behind it.

The brief was one principle: it should read as though a hundred FPL
experts worked on it, not as though an algorithm ranked a spreadsheet. In
practice that means three things have to hold, and these tests hold them:

  * every squad player is explained in specific prose, not a template
  * every transfer answers why-sell, why-buy, why-this-swap and what it
    does to the next month — and is willing to say "roll it" instead
  * nothing is claimed that the research does not support

The fourth thing, which is really the first, is that a page can fail its
own checks and say so rather than publishing confidently wrong advice.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.analysis import consensus, player_case, quality_control, transfer_case


def _row(**kw):
    base = {
        "id": 1, "web_name": "Palmer", "team_short_name": "CHE", "position": "MID",
        "price": 9.5, "selected_by_percent": 22.0, "xp_next": 5.0, "xp_horizon": 20.0,
        "status": "a",
    }
    base.update(kw)
    return pd.Series(base)


# --- player cards --------------------------------------------------------

def test_a_researched_player_gets_a_specific_case_not_a_template():
    frame = pd.DataFrame([dict(_row())])
    frame["consensus_for"] = consensus._pack(
        [{"point": "He is Chelsea's penalty taker and their main attacking midfielder",
          "source": "GOAL"}]
    )
    frame["predicted_start"] = "nailed"
    frame["set_pieces"] = "penalties and corners"
    frame["role_note"] = "the No.10, Chelsea's creative fulcrum"

    case = player_case.build(frame.iloc[0], gameweek=2, fixtures=[])
    text = case.write_up()

    assert "No.10" in text
    assert "penalt" in text
    assert "starts every week" in text
    assert case.source_count == 1


def test_two_different_players_do_not_produce_the_same_paragraph():
    """The specific failure the brief calls out: generic template sentences."""
    a = pd.DataFrame([dict(_row(web_name="A"))])
    a["consensus_for"] = consensus._pack([{"point": "He is on penalties", "source": "RotoWire"}])
    a["predicted_start"] = "nailed"

    b = pd.DataFrame([dict(_row(id=2, web_name="B", price=4.5))])
    b["predicted_start"] = "rotation risk"

    first = player_case.build(a.iloc[0], 2, fixtures=[], starting=True).write_up()
    second = player_case.build(b.iloc[0], 2, fixtures=[], starting=False).write_up()

    assert first != second
    assert "penalties" in first and "penalties" not in second
    assert "rotation risk" in second


def test_a_budget_enabler_is_described_as_one():
    """Dressing a fourth-choice defender up as a football pick insults the
    reader. Saying he is there to make the money work is honest."""
    frame = pd.DataFrame([dict(_row(price=4.0, position="DEF"))])
    case = player_case.build(frame.iloc[0], 2, fixtures=[], starting=False)

    assert case.enabler
    assert "make the budget work" in case.write_up()


def test_a_cheap_starter_is_not_called_an_enabler():
    """A £4.0m player who starts is a bargain, which is a different thing."""
    frame = pd.DataFrame([dict(_row(price=4.0, position="DEF"))])
    case = player_case.build(frame.iloc[0], 2, fixtures=[], starting=True)
    assert not case.enabler


def test_an_unresearched_player_says_so_rather_than_padding():
    frame = pd.DataFrame([dict(_row(web_name="Anon"))])
    case = player_case.build(frame.iloc[0], 2, fixtures=[])

    assert not case.researched
    assert "No outlet has written about him" in case.write_up()


def test_a_ruled_out_player_leads_with_that_and_nothing_else_matters():
    frame = pd.DataFrame([dict(_row())])
    frame["predicted_start"] = "out"
    case = player_case.build(frame.iloc[0], 2, fixtures=[])

    assert "not expected to play" in case.risk
    assert "Nothing else on this card matters" in case.risk


def test_a_template_player_is_told_the_ownership_cuts_both_ways():
    frame = pd.DataFrame([dict(_row(selected_by_percent=71.0))])
    case = player_case.build(frame.iloc[0], 2, fixtures=[])

    text = case.write_up()
    assert "protects your rank" in text
    assert "not owning him is the actual risk" in text


def test_disagreement_is_surfaced_as_disagreement():
    frame = pd.DataFrame([dict(_row())])
    frame["consensus_dissent"] = "Half the outlets think the role has changed."
    case = player_case.build(frame.iloc[0], 2, fixtures=[])

    assert "Sources disagree here" in case.write_up()


# --- captaincy -----------------------------------------------------------

def test_the_captain_gets_a_written_case_naming_the_alternative():
    frame = pd.DataFrame([dict(_row(selected_by_percent=71.0))])
    frame["consensus_for"] = consensus._pack(
        [{"point": "Palace are missing two of their back three", "source": "Sports Mole"}]
    )
    captain = player_case.build(frame.iloc[0], 2, fixtures=[], captain=True)
    vice = player_case.build(_row(id=2, web_name="Saka"), 2, fixtures=[], vice_captain=True)

    text = player_case.captaincy_reasoning(captain, vice)

    assert text.startswith("**Captaincy reasoning.**")
    assert "Saka" in text
    assert "safe armband" in text


def test_a_low_owned_captain_is_flagged_as_a_deliberate_differential():
    frame = pd.DataFrame([dict(_row(selected_by_percent=4.0))])
    text = player_case.captaincy_reasoning(
        player_case.build(frame.iloc[0], 2, fixtures=[], captain=True)
    )
    assert "differential armband" in text
    assert "deliberately rather than by accident" in text


def test_the_vice_is_labelled_correctly_not_title_cased():
    """`.title()` turns "vice-captaincy" into "Vice-Captaincy"."""
    text = player_case.captaincy_reasoning(
        player_case.build(_row(), 2, fixtures=[], vice_captain=True)
    )
    assert text.startswith("**Vice-captaincy reasoning.**")


# --- transfers -----------------------------------------------------------

def _pair():
    frame = pd.DataFrame([
        dict(_row(id=1, web_name="Out", xp_next=3.0, xp_horizon=10.0)),
        dict(_row(id=2, web_name="In", xp_next=6.0, xp_horizon=26.0)),
        dict(_row(id=3, web_name="Other", xp_next=5.4, xp_horizon=22.0)),
    ]).set_index("id", drop=False)
    frame["consensus_for"] = [None, consensus._pack(
        [{"point": "He is on penalties and playing as the No.10", "source": "GOAL"}]), None]
    frame["consensus_against"] = [consensus._pack(
        [{"point": "He has lost his place in the side", "source": "RotoWire"}]), None, None]
    frame["predicted_start"] = ["rotation risk", "nailed", "nailed"]
    frame["set_pieces"] = [None, "penalties", None]
    return frame


def test_a_transfer_answers_all_four_questions():
    frame = _pair()
    case = transfer_case.explain(frame, out_id=1, in_id=2, gameweek=2,
                                 alternative="Other (CHE, £9.5m), who projects 0.6 lower.")

    assert case.out.reasons and "lost his place" in case.out.reasons[0][0]
    assert case.into.reasons and "penalties" in case.into.reasons[0][0]
    assert "penalties" in case.why_this_swap
    assert "Other" in case.why_this_swap
    assert case.short_term
    assert case.look_ahead


def test_confidence_is_derived_and_hard_to_reach():
    frame = _pair()
    case = transfer_case.explain(frame, out_id=1, in_id=2, gameweek=2)
    # Researched, nailed and gaining over the horizon — but no fixture run
    # loaded, so it cannot be High.
    assert case.confidence == "Medium"


def test_an_incoming_rotation_risk_is_always_low_confidence_and_a_roll():
    frame = _pair()
    frame.loc[2, "predicted_start"] = "rotation risk"
    case = transfer_case.explain(frame, out_id=1, in_id=2, gameweek=2)

    assert case.confidence == "Low"
    assert case.roll_instead
    assert "not a certain starter" in case.roll_verdict


def test_rolling_is_recommended_when_the_gain_does_not_survive_the_horizon():
    """Preserving a transfer has value. A move that wins this week and
    loses over the month is one you have to undo."""
    frame = _pair()
    frame.loc[2, "xp_horizon"] = 5.0     # worse than the outgoing player
    case = transfer_case.explain(frame, out_id=1, in_id=2, gameweek=2)

    assert case.roll_instead
    assert "transferring back out again" in case.roll_verdict


def test_a_move_that_pays_over_the_horizon_is_recommended():
    frame = _pair()
    case = transfer_case.explain(frame, out_id=1, in_id=2, gameweek=2)
    assert not case.roll_instead
    assert "make the move" in case.roll_verdict


def test_the_alternative_names_a_real_player_and_the_gap():
    frame = _pair()
    cases = transfer_case.explain_plan(frame, [1], [2], gameweek=2)
    assert cases
    assert "Other" in cases[0].alternative
    assert "projects" in cases[0].alternative


# --- quality control -----------------------------------------------------

def _squad_frame(n=15, **overrides):
    rows = []
    for i in range(1, n + 1):
        row = dict(_row(id=i, web_name=f"P{i}",
                        position=["GKP", "DEF", "MID", "FWD"][i % 4]))
        row.update(overrides)
        rows.append(row)
    return pd.DataFrame(rows).set_index("id", drop=False)


def test_a_clean_week_passes_every_check():
    frame = _squad_frame()
    report = quality_control.run(list(range(1, 16)), frame, 2, bank=1.0, free_transfers=1)
    assert report.passed
    assert report.checks_run > 5


def test_a_ruled_out_player_in_the_squad_is_a_blocker():
    frame = _squad_frame()
    frame["predicted_start"] = "nailed"
    frame.loc[3, "predicted_start"] = "out"
    report = quality_control.run(list(range(1, 16)), frame, 2)

    assert not report.passed
    assert any("Ruled out" in f.detail for f in report.blockers)


def test_a_squad_from_a_later_gameweek_is_a_blocker():
    """Advice built on the wrong squad is advice for a team nobody owns."""
    frame = _squad_frame()
    report = quality_control.run(list(range(1, 16)), frame, 2, confirmed_event=5)

    assert not report.passed
    assert any("wrong starting point" in f.detail for f in report.blockers)


def test_a_negative_bank_is_a_blocker():
    frame = _squad_frame()
    report = quality_control.run(list(range(1, 16)), frame, 2, bank=-1.5)
    assert not report.passed


def test_a_defender_captain_is_a_blocker():
    frame = _squad_frame()
    cases = [player_case.build(_row(id=1, web_name="Gabriel", position="DEF"),
                               2, fixtures=[], captain=True)]
    report = quality_control.run(list(range(1, 16)), frame, 2, player_cases=cases)

    assert not report.passed
    assert any("Doubling a defender" in f.detail for f in report.blockers)


def test_a_thin_write_up_is_flagged_as_a_warning_not_a_blocker():
    frame = _squad_frame()
    cases = [player_case.build(_row(id=1, web_name="Anon", position="MID"),
                               2, fixtures=[], captain=True)]
    cases[0].arguments_for = [("x", "y")]        # satisfies the captaincy check
    cases[0].predicted_start = ""
    report = quality_control.run(list(range(1, 16)), frame, 2, player_cases=cases)

    assert report.passed or all(f.severity == quality_control.WARNING for f in report.findings)


def test_the_headline_says_what_needs_attention():
    frame = _squad_frame()
    report = quality_control.run(list(range(1, 16)), frame, 2, bank=-1.0)
    assert "need attention" in report.headline

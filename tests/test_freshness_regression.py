"""The two regressions this build exists to prevent, run on real data.

PART J is the failure that started it: a player transfers to Manchester
City and the app goes on showing START / MINUTES SECURE / CONFIDENCE
HIGH, because all three were computed from a record he built at Everton.

PART K is the failure the fix could easily cause: making every settled
starter uncertain because no journalist happened to write about him this
week, which would be just as useless in the opposite direction.

Neither test hard-codes an outcome. They assert the RULES against
whatever the committed decision file actually says, so a squad change
cannot make them pass vacuously and a genuine change of circumstance
cannot make them fail.
"""
import json
from pathlib import Path

import pytest

from fpl_assistant.analysis import status as ST

DECISION = Path(__file__).resolve().parent.parent / "data" / "research" / "decision.json"


@pytest.fixture(scope="module")
def decision():
    if not DECISION.exists():
        pytest.skip("no decision file committed")
    return json.loads(DECISION.read_text())


def statuses(decision):
    return decision.get("player_status") or {}


# --- PART J: a transfer resets role certainty ---------------------------

def test_every_recent_transfer_has_its_starting_security_reset(decision):
    """Whoever has moved, the rule is the same: a record earned elsewhere
    cannot make him nailed here."""
    moved = [(name, state) for name, state in statuses(decision).items()
             if state.get("new_club")]
    if not moved:
        pytest.skip("nobody in the squad has changed clubs")
    for name, state in moved:
        assert state["outlook"] != ST.VERY_LIKELY, (
            f"{name} has changed clubs and is still shown as very likely to "
            f"start")
        if not (state.get("fresh_source_count") or state.get("manager_reading")
                or (state.get("lineups") or {}).get("readable")):
            assert state["confidence"] != ST.HIGH, (
                f"{name} has changed clubs and is at high confidence with "
                f"nothing current behind it")


def test_a_transferred_player_is_flagged_on_the_page(decision):
    moved = [name for name, state in statuses(decision).items()
             if state.get("new_club")]
    if not moved:
        pytest.skip("nobody in the squad has changed clubs")
    coverage = decision.get("status_coverage") or {}
    assert set(moved) <= set(coverage.get("recent_transfers") or []), (
        "a recent transfer is not named in the coverage summary")


def test_the_app_is_capable_of_benching_a_player_it_had_starting(decision):
    """Not that it DOES — that the machinery can. If current evidence
    benches someone, nothing protects the old recommendation."""
    for name, state in statuses(decision).items():
        if (state.get("lineups") or {}).get("benched", 0) and not (
                state.get("lineups") or {}).get("starts", 0):
            assert state["outlook"] in (ST.LIKELY_BENCH, ST.VERY_UNLIKELY,
                                        ST.OUT, ST.FIFTY_FIFTY), (
                f"{name} is benched in every current predicted line-up and is "
                f"still shown as {state['outlook']}")


# --- PART K: silence does not make a settled starter uncertain ----------

def test_an_established_starter_is_not_downgraded_by_a_quiet_week(decision):
    for name, state in statuses(decision).items():
        if state.get("new_club") or state.get("injury") or state.get("suspension"):
            continue
        if state.get("availability") != "a":
            continue
        # Started essentially every game, at the club, with a real season
        # behind him: silence is normal and must not be read as doubt.
        if state.get("established") and state.get("starts", 0) >= max(
                1, state.get("team_games", 0) - 1):
            assert state["outlook"] in (ST.VERY_LIKELY, ST.LIKELY), (
                f"{name} is an established starter with nothing against him "
                f"and is shown as {state['outlook']}")
            assert state["confidence"] != ST.LOW, (
                f"{name} is an established starter shown at low confidence")


def test_the_squad_is_not_uniformly_uncertain(decision):
    """A page of fifteen 50-50s tells a manager nothing. If that is what
    comes out, the layer is not discriminating — it is shrugging."""
    outlooks = [state["outlook"] for state in statuses(decision).values()]
    if len(outlooks) < 5:
        pytest.skip("not a full squad")
    assert len(set(outlooks)) > 1, "every player has the same outlook"


# --- the state must be internally possible ------------------------------

def test_no_player_is_shown_in_an_impossible_state(decision):
    assert not (decision.get("status_validation") or {}), (
        decision.get("status_validation"))


def test_the_completeness_gate_covers_the_status_pass(decision):
    checks = (decision.get("completeness") or {}).get("checks") or {}
    assert "Current status checked for all 15" in checks
    assert "No impossible player states" in checks


def test_the_coverage_metric_counts_players_not_articles(decision):
    coverage = decision.get("status_coverage") or {}
    assert coverage, "no coverage metric was written"
    assert "articles" not in " ".join(str(v) for v in coverage)
    assert coverage.get("deadline_coverage") in ("GOOD", "PARTIAL", "THIN")


def test_every_squad_member_has_a_checked_status(decision):
    facts = decision.get("player_facts") or {}
    checked = statuses(decision)
    for name in facts:
        assert name in checked, f"{name} was never status-checked"


# --- the labels the page shows all come off the same status -------------

def test_the_minutes_label_on_the_card_agrees_with_the_outlook(decision):
    for name, state in statuses(decision).items():
        expected = ST.PlayerStatus.MINUTES_LABELS.get(state["outlook"])
        assert state.get("minutes_category") == expected, (
            f"{name}: card says {state.get('minutes_category')}, outlook is "
            f"{state['outlook']}")


def test_the_write_up_agrees_with_the_status(decision):
    """The specific contradiction: a card reading MINUTES SECURE above a
    write-up reading "likely bench"."""
    facts = decision.get("player_facts") or {}
    for name, state in statuses(decision).items():
        brief = (facts.get(name) or {}).get("brief") or {}
        if not brief:
            continue
        if state["outlook"] in (ST.LIKELY_BENCH, ST.VERY_UNLIKELY, ST.OUT):
            assert "nailed" not in brief.get("why", ""), (
                f"{name} is {state['outlook']} and his write-up calls him nailed")

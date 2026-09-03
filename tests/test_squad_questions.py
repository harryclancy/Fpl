"""Direct questions, answered from the state the page is already showing.

The point of these tests is not that the wording is right. It is that the
answer and the card underneath it cannot disagree — every answer is read
off the committed decision, so a test that changes the state and checks
the answer follows is testing the only property that matters.
"""
import pytest

from fpl_assistant.analysis import squad_questions as q


def decision(**overrides):
    base = {
        "player_status": {
            "Newman": {
                "outlook": "Likely bench", "confidence": "High",
                "minutes_label": "10-35 minutes", "expected_share": 0.28,
                "basis": "current predicted line-ups", "stale": False,
                "reasons": ["he has changed clubs"],
                "vetoes": ["current predicted line-ups overrule the record: "
                           "2 predicted line-up(s): 2 bench him"],
                "lineups": {"readable": 2, "starts": 0, "benched": 2,
                            "omitted": 0,
                            "summary": "2 predicted line-up(s): 2 bench him"},
                "evidence": [{"source": "Sports Mole", "title": "Predicted XI"}],
            },
            "Settled": {
                "outlook": "Very likely to start", "confidence": "Medium",
                "minutes_label": "75-90 minutes", "expected_share": 1.0,
                "basis": "the official appearance record", "stale": False,
                "reasons": ["he has started every game"], "vetoes": [],
                "lineups": {"readable": 0, "starts": 0, "benched": 0,
                            "omitted": 0, "summary": "no current predicted "
                                                     "line-up names him"},
                "evidence": [],
            },
        },
        "player_facts": {
            "Newman": {"brief": {"verdict_label": "BENCH, AND MONITOR",
                                 "why": "New to the club.", "case_for": "Good fixture.",
                                 "against": "The line-ups bench him.",
                                 "verdict": "Not enough certainty.",
                                 "confidence": "High", "run": "worsens",
                                 "next_four": ["COV (H)", "MUN (A)"]}},
            "Settled": {"brief": {"verdict_label": "START AND HOLD",
                                  "why": "Nailed.", "case_for": "Fixture is fine.",
                                  "against": "Nothing published against him.",
                                  "verdict": "Keep him.", "confidence": "Medium",
                                  "run": "improves",
                                  "next_four": ["SUN (H)", "BOU (A)"]}},
        },
        "recommendation": {"verdict": "Roll the transfer",
                           "winner": {"moves": [], "confidence": "High"},
                           "rejected": []},
        "explanation": {"problem": "Nothing needs fixing.",
                        "gain": "Keeping the transfer is worth 1.6.",
                        "changes": "A new injury would reopen this."},
        "sell_urgency_ranking": [
            {"player": "Newman", "sell_urgency": 55.0, "band": "Possible sell",
             "reasons": ["his minutes are a concern"]},
            {"player": "Settled", "sell_urgency": 5.0, "band": "Strong hold",
             "reasons": []},
        ],
    }
    base.update(overrides)
    return base


# --- routing -------------------------------------------------------------

@pytest.mark.parametrize("question,expected", [
    ("Will Newman start?", q.WILL_START),
    ("Is Newman starting?", q.WILL_START),
    ("Newman or Settled?", q.COMPARE),
    ("Why am I keeping Settled?", q.WHY_KEEP),
    ("Why sell Newman?", q.WHY_SELL),
    ("Who should I captain?", q.CAPTAIN),
    ("Should I roll?", q.WHY_ROLL),
    ("Who is my weakest player?", q.WEAKEST),
    ("Who should I sell?", q.WHO_SELL),
    ("Who is most at risk of not starting?", q.ROTATION_RISK),
    ("Who has the best next four?", q.BEST_RUN),
    ("Should I bench Newman?", q.SHOULD_START),
    ("Should I make Newman → Settled?", q.SHOULD_TRANSFER),
])
def test_every_supported_question_shape_routes(question, expected):
    assert q.intent(question) == expected


def test_a_comparison_is_not_mistaken_for_a_starting_question():
    assert q.intent("Should I start Newman or Settled?") == q.COMPARE


def test_players_are_matched_against_the_squad_in_the_order_asked():
    assert q.players_in("Newman or Settled?", ["Settled", "Newman"]) == [
        "Newman", "Settled"]


# --- the answer follows the state ---------------------------------------

def test_will_he_start_reads_the_current_status_not_a_write_up():
    answer = q.answer("Will Newman start?", decision())
    assert answer.call == "LIKELY BENCH"
    assert "Probably not" in answer.short_answer
    assert "2 bench him" in answer.why
    assert answer.expected_minutes == "10-35 minutes"
    assert answer.confidence == "High"


def test_the_same_question_flips_when_the_status_flips():
    """The property that matters: the answer is the state, not a cache."""
    state = decision()
    state["player_status"]["Newman"].update(
        outlook="Very likely to start", minutes_label="75-90 minutes",
        expected_share=1.0, vetoes=[],
        lineups={"readable": 2, "starts": 2, "benched": 0, "omitted": 0,
                 "summary": "2 predicted line-up(s): 2 start him"})
    answer = q.answer("Will Newman start?", state)
    assert answer.call == "VERY LIKELY TO START"
    assert "Yes" in answer.short_answer


def test_a_stale_status_is_declared_rather_than_dressed_up():
    state = decision()
    state["player_status"]["Newman"]["stale"] = True
    answer = q.answer("Will Newman start?", state)
    assert "Refresh Research" in answer.caveat


def test_a_comparison_prefers_the_player_more_likely_to_be_on_the_pitch():
    answer = q.answer("Newman or Settled?", decision())
    assert answer.call == "SETTLED"
    assert "Newman: 10-35 minutes" in answer.expected_minutes


def test_why_am_i_keeping_reads_the_write_up_and_the_plan():
    answer = q.answer("Why am I keeping Settled?", decision())
    assert answer.call == "START AND HOLD"
    assert "Keep him" in answer.why
    assert "Start And Hold" not in answer.short_answer   # no title-casing


def test_why_am_i_keeping_says_so_when_the_plan_sells_him():
    state = decision()
    state["recommendation"]["winner"]["moves"] = [
        {"out": "Newman", "in": "Someone"}]
    answer = q.answer("Why am I keeping Newman?", state)
    assert "does move him on" in answer.short_answer


def test_should_i_roll_agrees_with_the_transfer_plan():
    answer = q.answer("Should I roll?", decision())
    assert answer.call == "ROLL"

    acting = decision()
    acting["recommendation"] = {"verdict": "Newman → Someone",
                                "winner": {"moves": [{"out": "Newman",
                                                      "in": "Someone"}]},
                                "rejected": []}
    assert q.answer("Should I roll?", acting).call != "ROLL"


def test_a_refused_transfer_is_answered_with_the_reason_it_was_refused():
    state = decision()
    state["recommendation"]["rejected"] = [{
        "label": "Settled → Someone",
        "moves": [{"out": "Settled", "in": "Someone"}],
        "rejection_reasons": ["problem_fixed: Settled is not a problem"]}]
    answer = q.answer("Should I make Settled → Someone?", state)
    assert answer.call == "DO NOT MAKE THAT MOVE"
    assert "not a problem" in answer.why


def test_rotation_risk_ranks_by_how_likely_they_are_to_be_on_the_pitch():
    answer = q.answer("Who is most at risk of not starting?", decision())
    assert answer.players[0] == "Newman"
    assert answer.expected_minutes == "10-35 minutes"


def test_the_weakest_player_comes_off_the_sell_urgency_ranking():
    answer = q.answer("Who is my weakest player?", decision())
    assert "Newman" in answer.short_answer
    assert "55/100" in answer.short_answer


def test_captain_reads_the_verdict_rather_than_re_deciding():
    state = decision()
    state["player_facts"]["Settled"]["brief"]["verdict_label"] = "CAPTAIN"
    answer = q.answer("Who should I captain?", state)
    assert answer.short_answer == "Settled."


def test_an_unrecognised_question_says_so_rather_than_guessing():
    answer = q.answer("What is the airspeed velocity of a swallow?", decision())
    assert not answer.answered or "could not tell" in answer.short_answer


def test_the_suggestion_chips_are_questions_the_engine_can_route():
    for suggestion in q.SUGGESTIONS:
        assert q.intent(suggestion) != q.UNKNOWN, suggestion


def test_rotation_risk_only_considers_players_i_own():
    """`player_status` also carries every transfer target that was
    costed, so "who is most at risk" answered about a team nobody owns."""
    state = decision()
    state["player_status"]["Target"] = {
        "outlook": "Very unlikely to start", "confidence": "High",
        "minutes_label": "0-20 minutes", "expected_share": 0.1,
        "basis": "current predicted line-ups", "stale": False,
        "reasons": [], "vetoes": [],
        "lineups": {"readable": 1, "starts": 0, "benched": 0, "omitted": 1,
                    "summary": "1 leaves him out"}, "evidence": []}
    answer = q.answer("Who is most at risk of not starting?", state)
    assert "Target" not in answer.players
    assert "Target" not in answer.short_answer
    assert answer.players[0] == "Newman"


def test_a_player_expected_to_start_is_not_listed_as_at_risk():
    state = decision()
    state["player_status"]["Likely"] = {
        "outlook": "Likely to start", "confidence": "Medium",
        "minutes_label": "60-90 minutes", "expected_share": 0.88,
        "basis": "the official appearance record", "stale": False,
        "reasons": [], "vetoes": [],
        "lineups": {"readable": 0, "starts": 0, "benched": 0, "omitted": 0,
                    "summary": ""}, "evidence": []}
    state["player_facts"]["Likely"] = {"brief": {}}
    answer = q.answer("Who is most at risk of not starting?", state)
    assert "Likely" not in answer.players
    assert "Likely" not in (answer.caveat or "")

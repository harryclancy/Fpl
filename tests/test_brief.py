"""The player write-ups, tested as judgements rather than as strings.

Every test here is one of the questions the write-up is supposed to
answer. They are written against the REASONING — does it compare him to
a real alternative, does it look past this week, does the confidence it
prints match the evidence it has — because a test that asserts a
sentence's exact wording passes forever and tells you nothing about
whether the sentence was worth writing.
"""
import pytest

from fpl_assistant.analysis import brief as B


def player(**kw):
    base = dict(
        player="Player", club="ARS", club_name="Arsenal", position="MID",
        price=7.0, starts=2, minutes_played=180, team_games=2,
        prior_minutes=2700, prior_appearances=32,
        fixtures=[B.Fixture("CHE", True, 3.0), B.Fixture("SUN", False, 2.4),
                  B.Fixture("BHA", False, 3.0), B.Fixture("LEE", True, 2.4)],
        points_per_game=4.0, positional_ppg=3.1,
        five_gw=22.0, positional_five_gw=20.0)
    base.update(kw)
    return B.BriefInputs(**base)


def every_brief():
    """A spread wide enough that a rule cannot pass by luck."""
    return [
        B.build(player()),
        B.build(player(position="FWD", price=15.5, captain=True, penalties=True)),
        B.build(player(position="DEF", price=4.0, on_bench=True,
                       starts=0, minutes_played=0, prior_minutes=400,
                       prior_appearances=6, five_gw=5.0,
                       bench_alternatives=[B.Alternative("Someone", "starting", 20.0)])),
        B.build(player(position="GKP", price=5.0, availability="d",
                       chance_of_playing=50)),
        B.build(player(new_club_evidence="signed for Arsenal this summer")),
        B.build(player(points_per_game=0.5,
                       fixtures=[B.Fixture("MCI", False, 4.6),
                                 B.Fixture("LIV", False, 4.4),
                                 B.Fixture("ARS", True, 4.2),
                                 B.Fixture("CHE", False, 4.0)])),
    ]


# --- the eight questions the user asks of every write-up -----------------

def test_every_write_up_has_all_four_sections():
    for brief in every_brief():
        assert brief.why, brief.player
        assert brief.case_for, brief.player
        assert brief.against, brief.player
        assert brief.verdict, brief.player


def test_every_write_up_ends_in_a_decision_a_manager_can_act_on():
    labels = {B.START_HOLD, B.START_MONITOR, B.BENCH_HOLD, B.BENCH_MONITOR,
              B.KEEP_THROUGH, B.HOLD_REASSESS, B.SELL_IF, B.SELL_NOW,
              B.CAPTAIN_CALL, B.VICE_CALL}
    for brief in every_brief():
        assert brief.verdict_label in labels, brief.verdict_label


def test_every_write_up_contains_a_real_case_against():
    """Not a hedge — a specific thing that could make the decision wrong."""
    for brief in every_brief():
        assert len(brief.against.split()) >= 8, brief.against


def test_every_write_up_looks_past_this_week():
    for brief in every_brief():
        assert "→" in brief.verdict, brief.verdict


def test_every_write_up_is_the_length_of_an_argument_not_an_essay():
    for brief in every_brief():
        assert B.MIN_WORDS <= brief.words <= B.MAX_WORDS, (
            brief.player, brief.words)


def test_the_fixture_is_interpreted_rather_than_printed():
    """"SUN (H)" is a fact the manager already had."""
    brief = B.build(player(position="FWD", opponent_defence_rank=0.1,
                           fixtures=[B.Fixture("SUN", True, 2.0),
                                     B.Fixture("BOU", False, 3.0),
                                     B.Fixture("CHE", True, 3.0),
                                     B.Fixture("AVL", False, 3.0)]))
    assert "friendlier" in brief.case_for or "favourable" in brief.case_for
    assert "for an attacker" in brief.case_for


def test_a_defender_and_an_attacker_read_the_same_fixture_differently():
    fixtures = [B.Fixture("MCI", False, 4.5), B.Fixture("BUR", True, 2.0),
                B.Fixture("EVE", True, 2.4), B.Fixture("FUL", False, 2.6)]
    attacker = B.build(player(position="FWD", fixtures=fixtures))
    defender = B.build(player(position="DEF", fixtures=fixtures))
    assert "for an attacker" in attacker.case_for
    assert "for a clean sheet" in defender.case_for


# --- confidence has to be earned -----------------------------------------

def test_a_summer_signing_is_never_high_confidence():
    """A record built at another club proves nothing about this one."""
    brief = B.build(player(new_club_evidence="joined Arsenal this summer",
                           prior_minutes=3200, prior_appearances=36))
    assert brief.confidence != B.HIGH
    assert brief.playing != B.SECURE
    assert "new to the club" in brief.against


def test_a_transfer_resets_the_minutes_claim_however_good_the_record_is():
    settled = B.build(player())
    moved = B.build(player(new_club_evidence="joined Arsenal this summer"))
    assert settled.playing == B.SECURE
    assert moved.playing in (B.LIKELY, B.UNCERTAIN)
    assert "nailed" not in moved.why


def test_two_games_alone_does_not_earn_high_confidence():
    brief = B.build(player(prior_minutes=0, prior_appearances=0))
    assert brief.confidence == B.MEDIUM
    assert "not yet a pattern" in brief.against


def test_a_prior_season_at_the_same_club_does_earn_it():
    brief = B.build(player(prior_minutes=3000, prior_appearances=34))
    assert brief.confidence == B.HIGH
    assert "last year" in brief.why


def test_an_injury_flag_drops_confidence_and_the_decision():
    brief = B.build(player(availability="d", chance_of_playing=50))
    assert brief.confidence in (B.LOW, B.MEDIUM)
    assert brief.verdict_label in (B.START_MONITOR, B.HOLD_REASSESS)


# --- comparison, not isolation -------------------------------------------

def test_a_benched_player_is_told_who_he_is_behind():
    brief = B.build(player(
        on_bench=True, starts=0, minutes_played=0,
        bench_alternatives=[B.Alternative("Rival", "starting and secure", 25.0),
                            B.Alternative("Other", "", 22.0)]))
    assert "Rival" in brief.why
    assert brief.verdict_label.startswith("BENCH")


def test_a_kept_player_is_measured_against_the_transfer_he_would_be_sold_for():
    brief = B.build(player(transfer_alternatives=[B.Alternative(
        "Better", five_gw=28.0,
        rejected_because="nothing published argues against keeping him")]))
    assert "Better" in brief.verdict
    assert "refused" in brief.verdict


def test_a_marginal_replacement_is_named_as_not_worth_a_transfer():
    brief = B.build(player(transfer_alternatives=[
        B.Alternative("Barely", five_gw=22.5)]))
    assert "not enough to be worth a transfer" in brief.verdict


# --- a hard week is not automatically a sale -----------------------------

def test_one_hard_fixture_before_a_good_run_is_a_week_to_sit_through():
    brief = B.build(player(
        position="DEF", team_defence_rank=0.95, opponent_attack_rank=0.9,
        fixtures=[B.Fixture("CHE", True, 4.5), B.Fixture("SUN", False, 2.2),
                  B.Fixture("BHA", False, 2.6), B.Fixture("LEE", True, 2.2)]))
    assert brief.run == "improves"
    assert brief.verdict_label == B.KEEP_THROUGH
    assert "short-term" in brief.verdict


def test_a_kind_week_before_a_hard_run_says_so():
    brief = B.build(player(
        fixtures=[B.Fixture("BUR", True, 2.0), B.Fixture("MCI", False, 4.5),
                  B.Fixture("LIV", False, 4.4), B.Fixture("ARS", True, 4.2)]))
    assert brief.run == "worsens"
    assert "gets harder" in brief.verdict


# --- the page must not argue with itself ---------------------------------

NEGATIVE_IN_A_POSITIVE_SECTION = (
    "below par", "money is doing enough", "thin", "poor for the position")


def test_the_case_for_never_contains_the_case_against():
    for brief in every_brief():
        for phrase in NEGATIVE_IN_A_POSITIVE_SECTION:
            assert phrase not in brief.case_for, (brief.player, phrase)


def test_a_new_signing_is_never_called_a_settled_asset():
    brief = B.build(player(new_club_evidence="joined Arsenal this summer",
                           hold_strength=95.0))
    assert "settled asset" not in brief.verdict


def test_an_established_starter_is_not_also_called_a_small_sample():
    brief = B.build(player(prior_minutes=3000, prior_appearances=34))
    assert "not yet a pattern" not in brief.against


# --- grammar the reader would notice -------------------------------------

def test_prices_take_the_right_article():
    assert B._article(8.0) == "an"
    assert B._article(11.5) == "an"
    assert B._article(4.5) == "a"
    assert B._article(15.5) == "a"


def test_counts_read_as_english():
    assert B._count(2, whole=True) == "both games"
    assert B._count(1, "start") == "one start"
    assert B._count(3) == "three games"


def test_positions_are_named_not_abbreviated():
    brief = B.build(player(price=4.0, five_gw=5.0, positional_five_gw=20.0,
                           on_bench=True, starts=0, minutes_played=0))
    assert "MID" not in brief.against + brief.case_for


def test_a_side_is_never_described_with_a_broken_superlative():
    for rank in (0.0, 0.25, 0.5, 0.65, 0.85, 1.0):
        phrase = B._rank_phrase(rank, "strongest attacking", "strong attacking",
                                "weakest attacking", "weaker attacking")
        assert "a strongest" not in phrase
        assert "a weakest" not in phrase


# --- the wiring, not just the prose --------------------------------------
#
# These run the real assembly step against a synthetic FPL payload. A
# generator that writes beautiful prose from hand-built inputs proves
# nothing if the pipeline hands it zeros, which is exactly what the first
# live run of the previous engine did.

import importlib.util
from pathlib import Path

import pandas as pd

_spec = importlib.util.spec_from_file_location(
    "decide_transfers",
    Path(__file__).resolve().parent.parent / "scripts" / "decide_transfers.py")
decide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(decide)

from fpl_assistant.analysis import player_facts as pf
from fpl_assistant.analysis import squad_decision as sd
from fpl_assistant.analysis import strategy as st


def fake_live():
    teams = pd.DataFrame([
        {"id": 1, "name": "Arsenal", "short_name": "ARS",
         "strength_attack_home": 1300, "strength_attack_away": 1280,
         "strength_defence_home": 1340, "strength_defence_away": 1320},
        # Deliberately crossed over: Sunderland defend better than they
        # attack, Chelsea the reverse. A table where both orderings match
        # carries no directional information and is refused — see
        # test_undifferentiated_strength_ratings_are_refused.
        {"id": 2, "name": "Sunderland", "short_name": "SUN",
         "strength_attack_home": 1010, "strength_attack_away": 1000,
         "strength_defence_home": 1210, "strength_defence_away": 1190},
        {"id": 3, "name": "Chelsea", "short_name": "CHE",
         "strength_attack_home": 1260, "strength_attack_away": 1240,
         "strength_defence_home": 1060, "strength_defence_away": 1040},
    ]).set_index("id", drop=False)
    record = {
        "team": 1, "element_type": 2, "club": "ARS", "status": "a",
        "chance_of_playing_next_round": None, "starts": 2, "minutes": 180,
        "points_per_game": 4.5, "positional_baseline": 3.0, "total_points": 9,
        "xgi90": 0.22, "xgc90": 0.8, "defcon90": 9.5,
        "penalties": False, "set_pieces": True,
        "projection": 4.4, "five_gw": 21.4, "minutes_category": "Very secure",
    }
    return {
        "by_id": {10: record}, "by_name": {"Gabriel": record},
        "team_games": 2, "teams": teams,
        "strength_ranks": decide._strength_ranks(teams),
        "rate_medians": {(2, "xgi90"): 0.10, (2, "five_gw"): 18.0,
                         (2, "defcon90"): 7.0},
        "fixture_runs": {1: [
            {"opponent": "CHE", "opponent_id": 3, "home": True, "difficulty": 4.4},
            {"opponent": "SUN", "opponent_id": 2, "home": False, "difficulty": 2.2},
            {"opponent": "SUN", "opponent_id": 2, "home": True, "difficulty": 2.0},
            {"opponent": "CHE", "opponent_id": 3, "home": False, "difficulty": 3.0},
        ]},
        "fixture_labels": {1: ["CHE (H)", "SUN (A)", "SUN (H)", "CHE (A)"]},
        "fixture_table": {1: [4.4, 2.2, 2.0, 3.0]},
    }


def assembled():
    live = fake_live()
    signal = sd.PlayerSignals(
        name="Gabriel", club="ARS", position="DEF", price=8.0,
        minutes_category="Very secure", projection=4.4,
        gameweek_projections=[4.4] * 5, source_count=2)
    owner = {"id": 10, "name": "Gabriel", "position": "DEF", "on_bench": False,
             "is_captain": False, "is_vice_captain": False}
    facts = pf.build("Gabriel", "ARS", "DEF", 8.0)
    assessment = sd.assess(signal)
    state = st.SquadState(bank=0.0, free_transfers=1, event=3, squad_size=1,
                          selling_values={"Gabriel": 8.0})
    rejected = st.reject(st._plan("single", [st.Move(
        "Gabriel", "Calafiori", out_club="ARS", in_club="ARS",
        selling_value=8.0, buy_price=6.5, out_5gw=21.4, in_5gw=26.1)], state))
    rec = st.choose([st.roll_plan(state), rejected], state)
    return decide.brief_inputs(facts, signal, owner, live, rec, [assessment],
                               [owner], [rejected])


def test_the_pipeline_hands_the_generator_real_numbers():
    inputs = assembled()
    assert inputs.club_name == "Arsenal"
    assert inputs.starts == 2 and inputs.team_games == 2
    assert inputs.five_gw == 21.4
    assert inputs.defcon90 == 9.5 and inputs.set_pieces is True


def test_the_pipeline_supplies_a_real_fixture_run_with_opponents():
    inputs = assembled()
    assert [f.label for f in inputs.fixtures[:4]] == [
        "CHE (H)", "SUN (A)", "SUN (H)", "CHE (A)"]
    assert inputs.fixtures[0].difficulty == 4.4


def test_the_pipeline_ranks_the_clubs_against_the_league():
    inputs = assembled()
    # Arsenal have the best defence; Chelsea attack better than they
    # defend, which is exactly the distinction a single blunt rating
    # cannot make.
    assert inputs.team_defence_rank == 1.0
    assert inputs.opponent_attack_rank == 0.5
    assert inputs.opponent_defence_rank == 0.0


def test_the_pipeline_carries_the_prior_season_from_the_committed_history():
    minutes, appearances = decide.last_season("Haaland", "MCI")
    assert minutes > 1800 and appearances > 20
    # A player at a club he did not play for last season gets nothing,
    # which is the behaviour that makes a transfer reset the record.
    assert decide.last_season("Haaland", "ARS") == (0, 0)


def test_the_pipeline_names_the_transfer_the_engine_actually_refused():
    inputs = assembled()
    assert inputs.transfer_alternatives
    alternative = inputs.transfer_alternatives[0]
    assert alternative.name == "Calafiori"
    assert "share every fixture" in alternative.rejected_because


def test_the_assembled_brief_passes_the_quality_gate():
    judgement = B.build(assembled())
    assert decide.brief_quality(judgement) == [], judgement.as_dict()


def test_a_joining_line_is_read_from_published_text_not_inferred():
    facts = pf.build(
        "Ndiaye", "MCI", "MID", 6.0, full_name="Iliman Ndiaye",
        quotes=[{"text": "Iliman Ndiaye has joined Manchester City in a deal "
                         "worth a reported 40m, completing a move from Everton.",
                 "source": "Test", "tone": "neutral"}])
    assert "joined" in decide.joined_recently(facts)

    quiet = pf.build("Ndiaye", "MCI", "MID", 6.0, full_name="Iliman Ndiaye",
                     quotes=[{"text": "Ndiaye started and played the full 90 "
                                      "minutes on Saturday.", "source": "Test"}])
    assert decide.joined_recently(quiet) == ""


# --- defects the first live run of the briefs produced -------------------

def test_a_sentence_never_argues_with_itself_about_the_opponent():
    """"a favourable fixture, against one of the strongest defensive sides"
    reached the page: two independent FPL ratings disagreeing, both
    printed."""
    brief = B.build(player(position="FWD", opponent_defence_rank=0.95,
                           fixtures=[B.Fixture("SUN", True, 2.1),
                                     B.Fixture("BOU", False, 3.0),
                                     B.Fixture("CHE", True, 3.0),
                                     B.Fixture("AVL", False, 3.0)]))
    assert "strongest defensive" not in brief.case_for
    assert "favourable" in brief.case_for

    hard = B.build(player(position="DEF", opponent_attack_rank=0.05,
                          fixtures=[B.Fixture("MCI", False, 4.5),
                                    B.Fixture("BUR", True, 2.0),
                                    B.Fixture("EVE", True, 2.4),
                                    B.Fixture("FUL", False, 2.6)]))
    assert "least threatening" not in hard.case_for


def test_agreeing_ratings_are_still_quoted():
    brief = B.build(player(position="FWD", opponent_defence_rank=0.05,
                           fixtures=[B.Fixture("SUN", True, 2.1),
                                     B.Fixture("BOU", False, 3.0),
                                     B.Fixture("CHE", True, 3.0),
                                     B.Fixture("AVL", False, 3.0)]))
    assert "leakiest defensive" in brief.case_for


def test_a_worse_replacement_is_called_worse_not_marginal():
    brief = B.build(player(five_gw=35.0, transfer_alternatives=[
        B.Alternative("Weaker", five_gw=31.8)]))
    assert "LOWER" in brief.verdict
    assert "not enough to be worth a transfer" not in brief.verdict


def test_a_starter_is_compared_with_the_bench_not_with_other_starters():
    """A starting forward being told another starting forward projects
    higher is true, irrelevant, and not a decision he can act on."""
    live = fake_live()
    squad = [
        {"id": 10, "name": "Gabriel", "position": "DEF", "on_bench": False,
         "is_captain": False, "is_vice_captain": False},
        {"id": 11, "name": "Starter", "position": "DEF", "on_bench": False},
        {"id": 12, "name": "Benched", "position": "DEF", "on_bench": True},
    ]
    live["by_id"][11] = dict(live["by_id"][10], five_gw=40.0)
    live["by_id"][12] = dict(live["by_id"][10], five_gw=9.0)
    signal = sd.PlayerSignals(name="Gabriel", club="ARS", position="DEF",
                              price=8.0, gameweek_projections=[4.4] * 5)
    names = [a.name for a in decide._bench_alternatives(
        signal, squad[0], squad, live)]
    assert names == ["Benched"]

    benched = sd.PlayerSignals(name="Benched", club="ARS", position="DEF",
                               price=4.0, gameweek_projections=[1.0] * 5)
    names = [a.name for a in decide._bench_alternatives(
        benched, squad[2], squad, live)]
    assert "Gabriel" in names and "Benched" not in names


def test_undifferentiated_strength_ratings_are_refused_rather_than_quoted():
    """One number wearing two hats cannot say a side attacks well and
    defends badly, which is the only thing the clause is for."""
    degenerate = pd.DataFrame([
        {"id": 1, "name": "A", "short_name": "A",
         "strength_attack_home": 1200, "strength_attack_away": 1200,
         "strength_defence_home": 1200, "strength_defence_away": 1200},
        {"id": 2, "name": "B", "short_name": "B",
         "strength_attack_home": 1100, "strength_attack_away": 1100,
         "strength_defence_home": 1100, "strength_defence_away": 1100},
        {"id": 3, "name": "C", "short_name": "C",
         "strength_attack_home": 1000, "strength_attack_away": 1000,
         "strength_defence_home": 1000, "strength_defence_away": 1000},
    ]).set_index("id", drop=False)
    assert decide._strength_ranks(degenerate) == {}
    # A genuinely directional table still ranks.
    assert decide._strength_ranks(fake_live()["teams"])


def test_a_club_claim_is_omitted_when_there_is_no_rating_behind_it():
    brief = B.build(player(position="DEF", team_defence_rank=None,
                           opponent_attack_rank=None))
    assert "reliable source of clean sheets" not in brief.case_for
    assert "meanest" not in brief.case_for
    assert brief.case_for  # the fixture itself still carries the section


def test_the_quoted_gap_is_the_engines_own_figure():
    """The write-up quoted +1.1 while the reason under it quoted +5.0 —
    two separately-computed totals subtracted from each other."""
    brief = B.build(player(five_gw=26.1, transfer_alternatives=[
        B.Alternative("Barry", five_gw=31.1, delta=5.0,
                      rejected_because="nothing published argues against "
                                       "keeping him — a projection is a claim")]))
    assert "+5.0" in brief.verdict
    assert "+1.1" not in brief.verdict


def test_a_quoted_rejection_reason_does_not_repeat_the_sentence_around_it():
    brief = B.build(player(transfer_alternatives=[
        B.Alternative("Barry", five_gw=31.1, delta=5.0,
                      rejected_because="nothing published argues against "
                                       "keeping him — a projection is a claim, "
                                       "not evidence for it")]))
    assert "a projection is a claim" not in brief.verdict
    assert "nothing published argues against keeping him" in brief.verdict


def test_a_quoted_reason_does_not_restate_the_gap_twice():
    brief = B.build(player(transfer_alternatives=[
        B.Alternative("Barry", five_gw=31.1, delta=5.0,
                      rejected_because="the case for selling him is +5.0 over "
                                       "five gameweeks and nothing published "
                                       "argues against keeping him")]))
    assert brief.verdict.count("+5.0") == 1
    assert "nothing published argues against keeping him" in brief.verdict


def test_the_case_for_is_never_left_as_a_single_sentence_when_it_can_say_more():
    """A striker with cold numbers and a kind fixture still has an
    argument: he is the one on the pitch when the chances arrive."""
    brief = B.build(player(
        position="FWD", xgi90=0.0, positional_xgi90=0.0,
        five_gw=24.0, positional_five_gw=24.0, price=8.0,
        fixtures=[B.Fixture("SUN", True, 2.2), B.Fixture("BOU", False, 3.0),
                  B.Fixture("CHE", True, 3.0), B.Fixture("AVL", False, 3.0)]))
    assert brief.case_for.count(".") >= 2, brief.case_for
    assert "on the pitch when the chances come" in brief.case_for

"""The transfer decision engine: squad first, evidence only, roll always.

The failure being fixed: the engine asked "who is attractive to buy?" and
then found whoever the money worked against. That sells settled assets to
fund bandwagons, because the outgoing player was chosen by arithmetic
rather than because anything was wrong with him.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.analysis import squad_decision as sd


def player(name, **kw):
    base = dict(name=name, club="MCI", position="MID", price=7.0, projection=5.0)
    base.update(kw)
    return sd.PlayerSignals(**base)


# --- sell urgency --------------------------------------------------------

def test_no_player_is_protected_by_name():
    """Two identical records differing only in name must score identically.
    Reputation may not enter the arithmetic anywhere."""
    a = sd.assess(player("Haaland", price=15.5, points_per_game=8.0))
    b = sd.assess(player("Nobody", price=15.5, points_per_game=8.0))
    assert a.sell_urgency == b.sell_urgency
    assert a.hold_strength == b.hold_strength


def test_a_premium_asset_is_protected_by_his_evidence_not_his_price():
    settled = sd.assess(player("Premium", price=15.5, points_per_game=8.0,
                               positive_quotes=6, negative_quotes=0,
                               minutes_assessed=True, team_news_found=True,
                               penalties=True, fixture_scores=[2.0, 2.2, 2.4]))
    assert settled.band in ("Strong hold", "Comfortable hold")
    assert settled.hold_strength >= 65


def test_the_same_premium_becomes_sellable_when_the_evidence_turns():
    """The engine must be able to sell ANY player when circumstances change."""
    broken = sd.assess(player("Premium", price=15.5, points_per_game=8.0,
                              status="i", chance_of_playing=0,
                              injury_talk=True, negative_quotes=5,
                              minutes_assessed=True))
    assert broken.sell_urgency >= 91
    assert broken.forced


def test_current_news_outweighs_historic_output():
    """Excellent history plus current minutes uncertainty must still carry
    meaningful sell urgency."""
    great_history = player("X", points_per_game=7.0, omission_talk=True,
                           rotation_talk=True, transfer_talk=True,
                           negative_quotes=3, minutes_assessed=True)
    assert sd.assess(great_history).sell_urgency >= 46


def test_an_unresearched_player_is_uncertain_not_condemned():
    """Nobody writing about a squad player is not evidence he is bad. The
    old engine had no way to say that and quietly marked them down."""
    quiet = sd.assess(player("Quiet", evidence_count=0))
    injured = sd.assess(player("Injured", status="i", injury_talk=True))
    assert quiet.sell_urgency < injured.sell_urgency
    assert quiet.band in ("Comfortable hold", "Monitor")


def test_dead_money_on_the_bench_counts_as_a_problem():
    expensive_bench = sd.assess(player("Bench", price=6.0, on_bench=True))
    cheap_bench = sd.assess(player("Cheap", price=4.0, on_bench=True))
    assert expensive_bench.sell_urgency > cheap_bench.sell_urgency


# --- risk-adjusted expectation -------------------------------------------

def test_a_higher_projection_can_lose_to_a_secure_starter():
    """6.0 at 60% confidence must not automatically beat 5.5 nailed on.

    Availability now reaches the projection through the graded minutes
    category rather than through a pile of separate multipliers, so this
    is expressed as the categories the minutes model produces.
    """
    from fpl_assistant.analysis import minutes as m

    # Availability now lives INSIDE the projection — the expected-points
    # model applies expected minutes itself, so multiplying by the minutes
    # category again was a double count. What legitimately remains outside
    # the model is this week's reporting, so that is what separates these.
    risky = player("Risky", projection=6.0, minutes_category=m.SIGNIFICANT,
                   injury_talk=True, rotation_talk=True)
    secure = player("Secure", projection=5.5, minutes_category=m.VERY_SECURE,
                    team_news_found=True, positive_quotes=3)
    assert sd.risk_adjusted(secure) > sd.risk_adjusted(risky)


def test_the_horizon_is_front_loaded_but_looks_five_weeks_out():
    assert len(sd.HORIZON_WEIGHTS) == 5
    assert sd.HORIZON_WEIGHTS[0] > sd.HORIZON_WEIGHTS[-1]
    assert abs(sum(sd.HORIZON_WEIGHTS) - 1.0) < 0.01


# --- classification and the money question -------------------------------

def test_a_downgrade_whose_money_does_nothing_is_penalised():
    """Gabriel to De Cuyper is not an upgrade because De Cuyper is cheaper.
    If the released money does nothing, the move is worse, not better."""
    out = sd.assess(player("Strong", position="DEF", price=8.0,
                           positive_quotes=4, minutes_assessed=True,
                           team_news_found=True))
    into = player("Cheaper", club="BHA", position="DEF", price=5.7, projection=4.8)
    unspent = sd.build_option(out, into, bank=0.0)
    spent = sd.build_option(out, into, bank=0.0, money_enables="a midfield upgrade")
    assert unspent.classification == sd.BUDGET_RELEASE
    assert spent.score > unspent.score
    assert any("nothing was identified" in r for r in unspent.risks)


def test_a_forced_move_is_labelled_as_one():
    out = sd.assess(player("Injured", status="i", chance_of_playing=0,
                           injury_talk=True))
    option = sd.build_option(out, player("Fit", projection=5.0), bank=0.0)
    assert option.classification == sd.FORCED


# --- rolling -------------------------------------------------------------

def test_rolling_is_always_among_the_options():
    decision = sd.decide([player("A"), player("B")], targets=[], bank=0.0)
    assert any(o.kind == "roll" for o in decision.options)


def test_a_marginal_gain_loses_to_rolling():
    """The single most common mistake in this game is spending a free
    transfer for a fractional gain."""
    squad = [player("Owned", projection=5.0, minutes_assessed=True)]
    target = player("Marginal", club="LIV", projection=5.2, minutes_assessed=True)
    decision = sd.decide(squad, [target], bank=5.0)
    assert decision.winner.kind == "roll"
    assert any("not worth spending" in note for note in decision.sanity)


def test_a_clear_upgrade_beats_rolling():
    squad = [player("Weak", projection=2.0, status="i", chance_of_playing=0,
                    injury_talk=True, minutes_assessed=True)]
    target = player("Strong", club="LIV", projection=7.0, minutes_assessed=True,
                    team_news_found=True, positive_quotes=4, source_count=4,
                    fixture_scores=[2.0, 2.0, 2.2, 2.4, 2.5])
    squad[0].source_count = 4
    decision = sd.decide(squad, [target], bank=5.0)
    assert decision.winner.kind == "transfer"


# --- the mandatory question ----------------------------------------------

def test_one_target_is_tested_against_every_plausible_seller():
    """The specific fix: the old engine found a target then searched for a
    victim, and the victim was chosen by price."""
    squad = [player("A", projection=4.0), player("B", projection=4.5),
             player("C", projection=3.0)]
    decision = sd.decide(squad, [player("Target", club="LIV", projection=6.0)],
                         bank=10.0)
    sellers = {o.out_player for o in decision.options if o.kind == "transfer"}
    assert sellers == {"A", "B", "C"}, sellers


def test_the_engine_must_explain_why_this_player_and_not_the_next_two():
    squad = [player("A", projection=3.0, status="i", injury_talk=True),
             player("B", projection=5.0, positive_quotes=3),
             player("C", projection=4.0)]
    for p in squad:
        p.source_count = 3
        p.minutes_assessed = True
    decision = sd.decide(squad, [player("T", club="LIV", projection=7.0,
                                        minutes_assessed=True, source_count=3)],
                         bank=10.0)
    if decision.winner.kind == "transfer":
        explanation = sd.why_this_player_out(decision, decision.winner)
        assert decision.winner.out_player in explanation
        assert "Not " in explanation or "more obvious sale" in explanation


def test_selling_a_strong_asset_raises_a_sanity_warning():
    squad = [player("Strong", projection=6.0, positive_quotes=6, penalties=True,
                    minutes_assessed=True, team_news_found=True, source_count=4,
                    points_per_game=7.0, fixture_scores=[2.0, 2.0, 2.2])]
    decision = sd.decide(squad, [player("T", club="LIV", projection=9.0,
                                        minutes_assessed=True, source_count=4)],
                         bank=10.0)
    if decision.winner.kind == "transfer":
        assert any("hold strength" in n or "not a squad problem" in n
                   for n in decision.sanity)


# --- reversal and future cost --------------------------------------------

def test_selling_someone_you_will_want_back_is_penalised():
    strong = sd.assess(player("Strong", positive_quotes=6, penalties=True,
                              points_per_game=7.0, minutes_assessed=True,
                              team_news_found=True, fixture_scores=[2.0, 2.2]))
    risk, notes = sd.reversal_risk(strong, player("Other", club="LIV"))
    assert risk > 0
    assert any("buying him back" in n for n in notes)


def test_one_good_fixture_before_a_hard_run_is_penalised():
    cost, notes = sd.future_transfer_cost(
        player("Punt", club="LIV", fixture_scores=[2.0, 4.0, 4.2, 4.5, 4.0],
               minutes_assessed=True))
    assert cost > 0
    assert any("need reversing" in n for n in notes)


def test_a_hit_has_to_clear_its_own_cost():
    out = sd.assess(player("Out", projection=4.0))
    into = player("In", club="LIV", projection=5.0, minutes_assessed=True)
    free = sd.build_option(out, into, bank=5.0, hits=0)
    hit = sd.build_option(out, into, bank=5.0, hits=1)
    assert free.score - hit.score == sd.HIT_COST


# --- confidence ----------------------------------------------------------

def test_uncertainty_lowers_the_score():
    from fpl_assistant.analysis import minutes as m

    out = sd.assess(player("Out", projection=4.0, minutes_category=m.SECURE,
                           source_count=4))
    known = player("Known", club="LIV", projection=6.0,
                   minutes_category=m.SECURE, source_count=4)
    unknown = player("Unknown", club="LIV", projection=6.0,
                     minutes_category=m.UNASSESSED, source_count=0)
    assert sd.build_option(out, known, 5.0).score > sd.build_option(out, unknown, 5.0).score
    # Not High: neither player has any retrieved evidence behind him, and a
    # move is never more trustworthy than the projections underneath it.
    assert sd.build_option(out, known, 5.0).confidence == "Medium"
    assert sd.build_option(out, unknown, 5.0).confidence == "Low"


def test_an_unaffordable_move_is_rejected_not_scored():
    out = sd.assess(player("Cheap", price=4.0))
    option = sd.build_option(out, player("Expensive", club="LIV", price=12.0), bank=0.0)
    assert option.score < -50
    assert "unaffordable" in option.risks


def test_the_club_limit_is_respected():
    """Three from one club plus a player from elsewhere: selling the
    outsider and buying a fourth from the capped club is illegal. Selling
    one of the three and buying another from the same club is fine — the
    count stays at three — so only the first case may be rejected."""
    squad = [player(f"P{i}", club="MCI") for i in range(3)] + [player("Other", club="LIV")]
    decision = sd.decide(squad, [player("Target", club="MCI", projection=9.0)],
                         bank=20.0)
    sellers = {o.out_player for o in decision.options if o.kind == "transfer"}
    assert "Other" not in sellers, "that would put four Man City players in the squad"
    assert sellers, "swapping one Man City player for another is legal"


def test_the_checklist_is_binding_not_advisory():
    """The first full-input production run recommended selling a player its
    own sanity check called "not a squad problem being fixed". Printing the
    warning and recommending the move anyway is worse than not checking."""
    squad = [
        player("Settled", position="DEF", price=8.0, projection=5.0,
               positive_quotes=6, points_per_game=6.0, source_count=4,
               minutes_category="Very secure", minutes_confidence=1.0,
               team_news_found=True, fixture_scores=[2.0, 2.2, 2.4, 2.5, 2.6]),
        player("Problem", position="MID", price=6.0, projection=2.0,
               status="i", injury_talk=True, source_count=3,
               minutes_category="Major doubt", minutes_confidence=0.3),
    ]
    targets = [
        player("SlightlyBetterDef", club="BHA", position="DEF", price=6.0,
               projection=5.6, minutes_category="Secure", minutes_confidence=0.92,
               source_count=3),
        player("RealUpgrade", club="LIV", position="MID", price=7.0,
               projection=5.5, minutes_category="Secure", minutes_confidence=0.92,
               source_count=3),
    ]
    decision = sd.decide(squad, targets, bank=5.0)
    assert decision.winner.kind == "transfer"
    assert decision.winner.out_player == "Problem", (
        "the injured player is the squad problem; the settled asset is not"
    )


def test_a_strong_asset_is_not_sold_when_it_fixes_nothing():
    """The rejection path: the only move on offer sells a well-held player
    while nothing is wrong with him. The engine must fall back rather than
    print its own warning and proceed."""
    squad = [player("Settled", position="DEF", price=8.0, projection=5.0,
                    positive_quotes=6, points_per_game=6.0, source_count=4,
                    minutes_category="Very secure", minutes_confidence=1.0,
                    team_news_found=True, fixture_scores=[2.0, 2.2, 2.4])]
    targets = [player("Marginal", club="BHA", position="DEF", price=6.0,
                      projection=5.6, minutes_category="Secure",
                      minutes_confidence=0.92, source_count=3)]
    decision = sd.decide(squad, targets, bank=5.0)
    assert decision.winner.kind == "roll", decision.winner.label
    assert any("REJECTED" in n or "not worth spending" in n for n in decision.sanity), (
        decision.sanity
    )


def test_an_overwhelming_case_can_still_override_the_checklist():
    """Nothing is protected absolutely — but size alone is not enough.

    The override now needs CORROBORATION: something OBSERVED about the
    outgoing player, not merely a large number computed about him. Here
    the held player has a hard fixture run and cautionary reporting, which
    is the kind of evidence that earns an override.
    """
    # A realistic gap. Two points a gameweek between defenders is already
    # a big claim; the earlier fixture used five, which the outlier
    # detector correctly refused as not credible for a straight swap.
    squad = [player("Settled", position="DEF", price=8.0, projection=3.6,
                    positive_quotes=1, negative_quotes=4, points_per_game=6.0,
                    source_count=4, minutes_category="Very secure",
                    penalties=True, set_pieces=True, appearances=8, team_games=8,
                    fixture_scores=[4.2, 4.0, 4.5, 4.1, 4.0])]
    targets = [player("Elite", club="BHA", position="DEF", price=8.0,
                      projection=5.6, minutes_category="Very secure",
                      source_count=4, appearances=8, team_games=8,
                      fixture_scores=[2.0, 2.0, 2.0, 2.0, 2.0])]
    decision = sd.decide(squad, targets, bank=5.0)
    assert decision.winner.kind == "transfer", decision.sanity
    assert any("CORROBORATED" in n for n in decision.sanity), decision.sanity


def test_size_alone_cannot_override_a_hold():
    """The Gabriel case, generically. The model claimed a huge gain, the
    checklist objected, and the number was allowed to settle it. A number
    is not evidence about a footballer."""
    squad = [player("Settled", position="DEF", price=8.0, projection=2.0,
                    positive_quotes=6, points_per_game=6.0, source_count=4,
                    minutes_category="Very secure", team_news_found=True,
                    appearances=8, team_games=8,
                    fixture_scores=[2.2, 2.4, 2.3, 2.5, 2.4])]
    targets = [player("Shiny", club="BHA", position="DEF", price=6.0,
                      projection=9.0, minutes_category="Very secure",
                      source_count=4, appearances=8, team_games=8,
                      fixture_scores=[2.0, 2.0, 2.0, 2.0, 2.0])]
    decision = sd.decide(squad, targets, bank=5.0)
    assert decision.winner.kind == "roll", decision.winner.label
    assert any("only argument for the move is the model" in n
               for n in decision.sanity), decision.sanity


# --- calibration ---------------------------------------------------------

def test_fixtures_are_not_counted_twice():
    """The +15.66 bug. horizon_points used to shade an already
    fixture-adjusted projection by difficulty again, compounding across
    five gameweeks. Given the model's own per-gameweek series it must use
    it as-is."""
    series = [5.0, 5.0, 5.0, 5.0, 5.0]
    kind = player("Kind", gameweek_projections=series,
                  fixture_scores=[2.0, 2.0, 2.0, 2.0, 2.0])
    hard = player("Hard", gameweek_projections=series,
                  fixture_scores=[5.0, 5.0, 5.0, 5.0, 5.0])
    assert sd.horizon_points(kind) == sd.horizon_points(hard), (
        "difficulty is already inside the series; applying it again is a double count"
    )


def test_minutes_are_not_counted_twice():
    """The projection is built from expected minutes, so the category must
    not be applied again. Only news the model cannot see may discount it."""
    from fpl_assistant.analysis import minutes as m
    clean = player("Clean", gameweek_projections=[5.0], minutes_category=m.MAJOR_DOUBT)
    assert sd.risk_adjusted(clean) == 5.0, "the model already knows his minutes"
    reported = player("Reported", gameweek_projections=[5.0],
                      minutes_category=m.VERY_SECURE, injury_talk=True)
    assert sd.risk_adjusted(reported) < 5.0, "a knock reported this week is new information"


def test_a_thin_sample_is_shrunk_toward_the_positional_median():
    """Regressing against raw points-per-game fails exactly when needed. A
    defender who scored 17 in gameweek one has a rate of 8.5, so a
    projection of 8 looks reasonable against it — the rate is what is
    wrong."""
    hauler = player("Hauler", position="DEF", baseline=8.5, positional_baseline=2.5,
                    appearances=2, gameweek_projections=[8.2])
    assert sd.shrunk_baseline(hauler) < 5.0, sd.shrunk_baseline(hauler)
    regressed, note = sd.regress(hauler)
    assert regressed < 8.2
    assert "sample-shrunk baseline" in note


def test_an_established_player_keeps_his_own_rate():
    """Shrinkage must fade as the sample grows, or it would flatten a
    genuinely elite player all season."""
    proven = player("Proven", baseline=8.0, positional_baseline=3.0, appearances=30)
    assert sd.shrunk_baseline(proven) > 7.0


def test_plausibility_bands_flag_an_extreme_swing():
    assert sd.plausibility(2.0) == "small edge"
    assert sd.plausibility(8.0) == "strong"
    assert "audited" in sd.plausibility(20.0)


def test_projection_confidence_falls_with_the_sample():
    thin = player("Thin", appearances=1, team_games=8, minutes_category="Unassessed")
    solid = player("Solid", appearances=8, team_games=8, minutes_category="Very secure",
                   evidence_count=5, baseline=5.0, positional_baseline=4.0,
                   gameweek_projections=[5.5])
    assert sd.projection_confidence(thin) == sd.LOW
    assert sd.projection_confidence(solid) == sd.HIGH

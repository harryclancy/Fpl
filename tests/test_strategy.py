"""The transfer decision architecture, tested on the failures that caused it.

Each of the first four tests is a recommendation the old engine actually
produced and could not explain. They are written against the RULES, not
against the players — no test here asserts anything about a named
footballer, so a change of squad cannot make them pass vacuously.
"""
import pytest

from fpl_assistant.analysis import squad_decision as sd
from fpl_assistant.analysis import strategy as st


def signals(name, club="Arsenal", position="DEF", price=6.0, projection=5.0,
            **kw):
    return sd.PlayerSignals(
        name=name, club=club, position=position, price=price,
        projection=projection,
        gameweek_projections=kw.pop("series", [projection] * 5),
        appearances=kw.pop("appearances", 10),
        minutes_played=kw.pop("minutes_played", 900),
        team_games=kw.pop("team_games", 10),
        source_count=kw.pop("source_count", 3),
        minutes_category=kw.pop("minutes_category", "Secure"),
        **kw)


def state(bank=1.0, free_transfers=1, names=(), values=None):
    """A complete 15-man state, so incompleteness is never the reason a
    test passes. Named players keep their given selling values."""
    full = {f"Filler {i}": 5.0 for i in range(15)}
    for index, name in enumerate(names):
        full.pop(f"Filler {index}", None)
        full[name] = (values or {}).get(name, 6.0)
    for name, value in (values or {}).items():
        full[name] = value
    while len(full) > 15:
        full.pop(next(k for k in full if k.startswith("Filler")))
    return st.SquadState(bank=bank, free_transfers=free_transfers, event=3,
                         squad_size=len(full),
                         selling_values=full, purchase_values=dict(full))


def plan_of(out_sig, in_sig, s, reasons=(), **kw):
    assessment = sd.assess(out_sig)
    move = st.build_move(assessment, in_sig, s, list(reasons))
    plan = st._plan(kw.pop("kind", "single"), [move], s, **kw)
    return st.reject(plan)


# --- failure 1: a same-club swap justified by shared fixtures -------------

def test_same_club_move_cannot_be_justified_by_club_level_evidence():
    """Two defenders at the same club share every fixture. Saying the club
    has a good run says nothing about which of them to own."""
    out = signals("Owned Defender", club="Arsenal")
    into = signals("Other Defender", club="Arsenal", projection=5.6)
    s = state(names=["Owned Defender"], values={"Owned Defender": 6.0})
    club_reason = st.Reason("Arsenal have a kind run of fixtures",
                            about="Owned Defender", level=st.CLUB_LEVEL,
                            kind=st.STATISTIC)
    plan = plan_of(out, into, s, [club_reason])
    assert plan.rejected
    assert any("same_club" in r for r in plan.rejection_reasons)


def test_same_club_move_survives_on_a_player_level_difference():
    out = signals("Owned Defender", club="Arsenal", minutes_category="Slight risk")
    into = signals("Other Defender", club="Arsenal", projection=10.0,
                   set_pieces=True)
    s = state(names=["Owned Defender"], values={"Owned Defender": 6.0})
    reasons = [
        st.Reason("has taken every corner since the opening weekend",
                  about="Other Defender", level=st.PLAYER_LEVEL, kind=st.FACT,
                  direction="buy"),
        st.Reason("was substituted at half time on Saturday",
                  about="Owned Defender", level=st.PLAYER_LEVEL, kind=st.FACT,
                  direction="sell"),
    ]
    plan = plan_of(out, into, s, reasons)
    assert not any("same_club" in r for r in plan.rejection_reasons)


def test_club_level_evidence_is_admissible_between_different_clubs():
    """The rule is about identical fixtures, not about club-level facts."""
    move = st.Move("A", "B", out_club="Arsenal", in_club="Chelsea")
    reason = st.Reason("Arsenal have the best defensive record",
                       about="A", level=st.CLUB_LEVEL, kind=st.STATISTIC)
    kept, excluded = st.admissible([reason], move)
    assert kept and not excluded


# --- failure 2: evidence about somebody else -----------------------------

def test_evidence_about_a_third_player_is_excluded():
    move = st.Move("Owned Winger", "Target Winger",
                   out_club="Bournemouth", in_club="Arsenal")
    reason = st.Reason("Foden and Cherki are the preferred City picks",
                       about="Foden", level=st.PLAYER_LEVEL, kind=st.EXPERT)
    kept, excluded = st.admissible([reason], move)
    assert kept == []
    assert excluded and "not part of this move" in excluded[0]


def test_a_move_with_no_admissible_evidence_is_rejected():
    out = signals("Owned Winger", club="Bournemouth", position="MID")
    into = signals("Target Winger", club="Arsenal", position="MID",
                   projection=7.0)
    s = state(names=["Owned Winger"], values={"Owned Winger": 6.0})
    third_party = st.Reason("Two other players are preferred picks",
                            about="Someone Else", kind=st.EXPERT)
    plan = plan_of(out, into, s, [third_party])
    assert plan.rejected
    assert any("evidence_exists" in r for r in plan.rejection_reasons)


# --- failure 3: selling a strong hold on a projection alone --------------

def test_a_strong_hold_cannot_be_sold_on_a_projection_alone():
    out = signals("Strong Asset", club="Arsenal", projection=6.0,
                  minutes_category="Very secure", starts=10, form=6.0,
                  points_per_game=6.0, baseline=6.0, positive_quotes=4,
                  evidence_count=6, minutes_assessed=True, team_news_found=True)
    into = signals("Shiny Alternative", club="Brighton", projection=9.0,
                   source_count=3)
    s = state(names=["Strong Asset"], values={"Strong Asset": 6.0})
    reason = st.Reason("projected to score more", about="Shiny Alternative",
                       kind=st.INFERENCE)
    assessment = sd.assess(out)
    plan = plan_of(out, into, s, [reason])
    if assessment.hold_strength >= st.STRONG_HOLD:
        assert plan.rejected
        assert any("corroboration" in r or "problem_fixed" in r
                   for r in plan.rejection_reasons)


def test_a_hit_must_clear_four_points_not_match_them():
    out = signals("Owned", club="Arsenal")
    into = signals("Target", club="Brighton", projection=6.0)
    s = state(free_transfers=0, names=["Owned"], values={"Owned": 6.0})
    reason = st.Reason("started every game", about="Target", kind=st.FACT)
    plan = plan_of(out, into, s, [reason])
    assert plan.hit == 4.0
    if plan.gross_5gw < 6.0:
        assert plan.rejected
        assert any("hit_cleared" in r or "net_positive" in r
                   for r in plan.rejection_reasons)


# --- failure 4: roll must be a real option, neither forced nor ignored ---

def test_roll_wins_when_no_move_clears_the_margin():
    s = state(names=["A"], values={"A": 6.0})
    roll = st.roll_plan(s)
    weak = st._plan("single", [st.Move("A", "B", selling_value=6.0,
                                       buy_price=6.0, out_5gw=25.0,
                                       in_5gw=26.0)], s)
    rec = st.choose([roll, weak], s)
    assert not rec.acting
    assert rec.verdict == "Roll the transfer"


def test_roll_loses_to_a_clearly_better_move():
    s = state(names=["A"], values={"A": 6.0})
    roll = st.roll_plan(s)
    strong = st._plan("single", [st.Move("A", "B", selling_value=6.0,
                                         buy_price=6.0, out_5gw=20.0,
                                         in_5gw=30.0)], s)
    rec = st.choose([roll, strong], s)
    assert rec.acting
    assert rec.out_names == {"A"}


def test_roll_is_not_forced_to_win_by_its_own_value():
    """Rolling carries option value, not a veto. A real upgrade beats it."""
    assert st.ROLL_VALUE < st.HIT_COST
    s = state(names=["A"], values={"A": 6.0})
    # A four-point five-gameweek gain is an ordinary good transfer, not an
    # outlier. If rolling survived that, rolling would always win.
    good = st._plan("single", [st.Move("A", "B", selling_value=6.0,
                                       buy_price=6.0, out_5gw=20.0,
                                       in_5gw=24.0)], s)
    assert st.choose([st.roll_plan(s), good], s).acting


# --- arithmetic ----------------------------------------------------------

def test_selling_value_not_market_price_is_used():
    out = signals("Risen Asset", price=7.5)
    into = signals("Target", club="Brighton", price=7.2)
    s = state(bank=0.0, names=["Risen Asset"],
              values={"Risen Asset": 7.2})   # half the rise returned
    move = st.build_move(sd.assess(out), into, s)
    assert move.selling_value == 7.2
    assert move.cash_delta == 0.0


def test_unaffordable_plan_is_rejected_and_never_recommended():
    s = state(bank=0.0, names=["Owned"], values={"Owned": 5.0})
    move = st.Move("Owned", "Expensive", selling_value=5.0, buy_price=9.0)
    plan = st.reject(st._plan("single", [move], s))
    assert plan.rejected
    assert any("affordable" in r for r in plan.rejection_reasons)
    rec = st.choose([st.roll_plan(s), plan], s)
    assert not rec.acting


def test_hit_is_subtracted_from_the_deciding_number():
    s = state(free_transfers=1, names=["A", "B"],
              values={"A": 6.0, "B": 6.0})
    moves = [st.Move("A", "C", selling_value=6.0, buy_price=6.0,
                     out_5gw=20.0, in_5gw=23.0),
             st.Move("B", "D", selling_value=6.0, buy_price=6.0,
                     out_5gw=20.0, in_5gw=23.0)]
    plan = st._plan("package", moves, s)
    assert plan.paid_transfers == 1
    assert plan.hit == 4.0
    assert plan.gross_5gw == 6.0
    assert plan.net_5gw == pytest.approx(2.0)
    assert not st.verify_arithmetic(plan)


def test_bank_after_follows_from_the_moves():
    s = state(bank=1.5, names=["A"], values={"A": 6.0})
    move = st.Move("A", "B", selling_value=6.0, buy_price=5.0)
    plan = st._plan("single", [move], s)
    assert plan.bank_after == 2.5
    assert not st.verify_arithmetic(plan)


def test_free_transfers_carry_and_cap():
    s = state(free_transfers=5, names=["A"], values={"A": 6.0})
    assert st.roll_plan(s).free_transfers_after == 5


def test_missing_selling_prices_make_the_state_incomplete():
    s = st.SquadState(bank=1.0, free_transfers=1, event=3, squad_size=2,
                      selling_values={"A": 6.0, "B": 0.0})
    assert not s.complete
    rec = st.choose([st.roll_plan(s)], s)
    assert rec.verdict == "INCOMPLETE — REQUIRED DATA MISSING"
    assert st.explain(rec)["headline"].startswith("INCOMPLETE")


# --- contradiction scan --------------------------------------------------

def test_page_that_says_make_the_move_while_rolling_is_caught():
    s = state(names=["A"], values={"A": 6.0})
    rec = st.choose([st.roll_plan(s)], s)
    clashes = st.contradictions(rec, [("A's card", "Clear upgrade — make the move.")])
    assert clashes and "roll" in clashes[0]


def test_page_that_says_sell_a_player_the_plan_keeps_is_caught():
    s = state(names=["A"], values={"A": 6.0})
    strong = st._plan("single", [st.Move("A", "B", selling_value=6.0,
                                         buy_price=6.0, out_5gw=20.0,
                                         in_5gw=30.0)], s)
    rec = st.choose([st.roll_plan(s), strong], s)
    clashes = st.contradictions(rec, [("C's card", "C is done — time to sell.")])
    assert clashes == [] or all("C" in c for c in clashes)


def test_consistent_page_produces_no_contradictions():
    s = state(names=["A"], values={"A": 6.0})
    rec = st.choose([st.roll_plan(s)], s)
    assert st.contradictions(rec, [("A's card", "Holding. Nothing has changed.")]) == []


# --- one answer ----------------------------------------------------------

def test_only_one_plan_is_the_recommendation():
    s = state(names=["A"], values={"A": 6.0})
    strong = st._plan("single", [st.Move("A", "B", selling_value=6.0,
                                         buy_price=6.0, out_5gw=20.0,
                                         in_5gw=30.0)], s)
    second = st._plan("single", [st.Move("A", "C", selling_value=6.0,
                                         buy_price=6.0, out_5gw=20.0,
                                         in_5gw=27.0)], s)
    rec = st.choose([st.roll_plan(s), strong, second], s)
    assert rec.winner is strong
    assert strong not in rec.alternatives
    assert second in rec.alternatives


def test_close_call_is_declared_rather_than_hidden():
    s = state(names=["A"], values={"A": 6.0})
    marginal = st._plan("single", [st.Move("A", "B", selling_value=6.0,
                                           buy_price=6.0, out_5gw=20.0,
                                           in_5gw=23.2)], s)
    rec = st.choose([st.roll_plan(s), marginal], s)
    assert rec.close_call
    assert any("CLOSE CALL" in n for n in rec.notes)


def test_rejected_plans_are_visible_but_never_the_winner():
    s = state(names=["A"], values={"A": 6.0})
    bad = st.reject(st._plan("single", [st.Move("A", "B", selling_value=6.0,
                                                buy_price=99.0)], s))
    rec = st.choose([st.roll_plan(s), bad], s)
    assert bad in rec.rejected
    assert rec.winner is not bad


# --- the audit -----------------------------------------------------------

def test_trust_audit_has_ten_questions_and_passes_a_clean_decision():
    s = state(names=["A"], values={"A": 6.0})
    rec = st.choose([st.roll_plan(s)], s)
    checks = st.trust_audit(rec, [("A's card", "Holding.")])
    assert len(checks) == 10
    assert st.audit_passed(checks), [c for c in checks if not c[1]]


def test_trust_audit_fails_on_a_contradictory_page():
    s = state(names=["A"], values={"A": 6.0})
    rec = st.choose([st.roll_plan(s)], s)
    checks = st.trust_audit(rec, [("A's card", "Make the move.")])
    assert not st.audit_passed(checks)


def test_explanation_answers_the_decision_not_the_players():
    s = state(names=["A"], values={"A": 6.0})
    rec = st.choose([st.roll_plan(s)], s)
    text = st.explain(rec)
    assert set(text) == {"headline", "problem", "gain", "cost", "changes"}
    assert text["headline"] == "Roll the transfer"
    assert "transfer" in text["gain"]


def test_a_card_recommending_a_sale_no_plan_makes_is_caught():
    """The player need not appear in any plan for this to be a clash."""
    s = state(names=["A"], values={"A": 6.0})
    rec = st.choose([st.roll_plan(s)], s)
    clashes = st.contradictions(
        rec, [("Unrelated card", "Unrelated is the one to move on.")],
        known_names={"Unrelated"})
    assert clashes and "Unrelated" in clashes[0]


def test_gameweek_one_gain_is_read_from_the_series_not_averaged():
    """A move that is all upside in week one must not look spread out."""
    s = state(names=["A"], values={"A": 6.0})
    move = st.Move("A", "B", selling_value=6.0, buy_price=6.0,
                   out_series=[2.0, 5.0, 5.0, 5.0, 5.0],
                   in_series=[9.0, 5.0, 5.0, 5.0, 5.0],
                   out_5gw=22.0, in_5gw=29.0)
    plan = st._plan("single", [move], s)
    assert plan.gain_gw1 == 7.0
    assert plan.gain_3gw == 7.0
    assert plan.gross_5gw == 7.0


def test_reversal_risk_is_subtracted_from_the_deciding_number():
    s = state(names=["A"], values={"A": 6.0})
    move = st.Move("A", "B", selling_value=6.0, buy_price=6.0,
                   out_5gw=20.0, in_5gw=25.0, reversal_risk=2.0)
    plan = st._plan("single", [move], s)
    assert plan.gross_5gw == 5.0
    assert plan.net_5gw == 3.0


def test_conservative_selling_values_are_still_a_complete_state():
    """Unknown split, known total: usable, and labelled as what it is."""
    s = state(names=["A"], values={"A": 5.9})
    s.selling_basis = "conservative"
    assert s.complete
    rec = st.choose([st.roll_plan(s)], s)
    checks = st.trust_audit(rec, [])
    assert checks[0][1]
    assert "conservative" in checks[0][2]


def test_a_zero_selling_value_is_still_missing_data():
    s = state(names=["A"], values={"A": 0.0})
    assert not s.complete
    assert any("no selling price" in m for m in s.missing)


# --- the live failure: a 0/100 hold sold on a projection alone -----------

def test_a_player_with_no_problem_cannot_be_sold_however_big_the_projection():
    """The live run recommended exactly this before the rule existed."""
    s = state(names=["Settled"], values={"Settled": 8.0})
    move = st.Move("Settled", "Cheap Alternative", position="DEF",
                   out_club="Arsenal", in_club="Brighton",
                   selling_value=8.0, buy_price=4.5,
                   out_5gw=21.4, in_5gw=27.9,
                   out_urgency=0.0, out_hold=55.0,
                   out_minutes="Very secure", in_minutes="Very secure",
                   confidence="Medium")
    plan = st.reject(st._plan("single", [move], s))
    assert plan.rejected
    assert any("problem_fixed" in r for r in plan.rejection_reasons)
    assert "projection" in plan.rejection_reasons[0]


def test_the_same_move_survives_once_something_is_observed_about_both():
    s = state(names=["Settled"], values={"Settled": 8.0})
    move = st.Move("Settled", "Cheap Alternative", position="DEF",
                   out_club="Arsenal", in_club="Brighton",
                   selling_value=8.0, buy_price=4.5,
                   out_5gw=21.4, in_5gw=27.9,
                   out_urgency=40.0, out_hold=40.0,
                   out_minutes="Very secure", in_minutes="Very secure",
                   confidence="Medium")
    move.reasons = [
        st.Reason("has been moved to right-back for the last three games",
                  about="Settled", level=st.PLAYER_LEVEL, kind=st.FACT,
                  direction="sell"),
        st.Reason("has started every league game and taken the corners",
                  about="Cheap Alternative", level=st.PLAYER_LEVEL,
                  kind=st.FACT, direction="buy"),
    ]
    plan = st.reject(st._plan("single", [move], s))
    assert not plan.rejected, plan.rejection_reasons


def test_a_large_projection_needs_corroboration_on_the_incoming_player_too():
    s = state(names=["Settled"], values={"Settled": 8.0})
    move = st.Move("Settled", "Unknown Quantity", position="DEF",
                   out_club="Arsenal", in_club="Brighton",
                   selling_value=8.0, buy_price=4.5,
                   out_5gw=21.4, in_5gw=27.9,
                   out_urgency=40.0, out_hold=40.0,
                   out_minutes="Very secure", in_minutes="Very secure",
                   confidence="Medium")
    move.reasons = [st.Reason("was dropped on Saturday", about="Settled",
                              level=st.PLAYER_LEVEL, kind=st.FACT,
                              direction="sell")]
    plan = st.reject(st._plan("single", [move], s))
    assert plan.rejected
    assert any("corroboration" in r for r in plan.rejection_reasons)


# --- the live failure: evidence that argues the other way ----------------

def test_a_favourable_item_cannot_corroborate_a_sale():
    """The live run cited 'he very likely starts, as he always does' as a
    reason to sell him, because it named him and concerned his minutes."""
    s = state(names=["Owned"], values={"Owned": 8.5})
    move = st.Move("Owned", "Target", position="MID",
                   out_club="Bournemouth", in_club="Forest",
                   selling_value=8.5, buy_price=8.0,
                   out_5gw=24.5, in_5gw=30.1,
                   out_urgency=0.0, out_hold=64.0,
                   out_minutes="Very secure", in_minutes="Very secure",
                   confidence="Medium")
    move.reasons = [
        st.Reason("very likely starts, as he always does, but two rivals are "
                  "cheaper", about="Owned", level=st.PLAYER_LEVEL,
                  kind=st.EXPERT, direction="buy"),
        st.Reason("scored again at the weekend", about="Target",
                  level=st.PLAYER_LEVEL, kind=st.FACT, direction="buy"),
    ]
    plan = st.reject(st._plan("single", [move], s))
    assert plan.rejected
    assert any("argues against keeping him" in r for r in plan.rejection_reasons)


def test_direction_is_read_from_the_claim_not_from_the_topic():
    from fpl_assistant.analysis import player_facts as pf
    keep = pf.classify(
        "Antoine Semenyo (\u00a38.5m) very likely starts, as he always does, "
        "but Phil Foden (\u00a37.0m) is cheaper.",
        "Semenyo", "BOU", "Antoine Semenyo")
    drop = pf.classify("Semenyo was left out of the squad with a hamstring "
                       "injury.", "Semenyo", "BOU", "Antoine Semenyo")
    assert keep is not None and keep.direction != "sell"
    assert drop is not None and drop.direction == "sell"

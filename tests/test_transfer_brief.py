"""The transfer, argued — tested as reasoning rather than as prose.

The old transfer section answered "why is the incoming player good",
which is not the decision. These tests check that the write-up answers
the decision: why this player out, why this one in, why now, why not
roll, what it costs, and what could make it wrong.

Nothing here asserts a sentence. Each test asserts a property the
argument must have, so the wording can improve without the tests
becoming a transcript of it.
"""
import pytest

from fpl_assistant.analysis import strategy as st
from fpl_assistant.analysis import transfer_brief as tb

EASY = [("BUR (H)", 2.0), ("SHU (A)", 2.2), ("EVE (H)", 2.4),
        ("FUL (A)", 2.6), ("LUT (H)", 2.2)]
HARD = [("MCI (A)", 4.6), ("LIV (H)", 4.4), ("ARS (A)", 4.2),
        ("CHE (H)", 4.0), ("TOT (A)", 3.8)]
MIXED = [("SUN (H)", 2.2), ("BOU (A)", 3.2), ("CHE (H)", 4.2),
         ("AVL (A)", 3.6), ("NEW (H)", 3.4)]


def side(name, club="CHE", pos="MID", price=7.0,
         outlook="Very likely to start", minutes="75-90 minutes",
         urgency=10.0, hold=40.0, five=22.0, fixtures=MIXED, **kw):
    return tb.Side(name=name, club=club, position=pos, price=price,
                   outlook=outlook, minutes_label=minutes,
                   sell_urgency=urgency, hold_strength=hold, five_gw=five,
                   fixtures=list(fixtures), **kw)


def state(bank=0.5, free_transfers=1, sells=None):
    """A squad state whose selling values cover the players under test.

    Without them a move is unaffordable, and the affordability check
    fires before anything else — correctly, but it hides the rule the
    test is actually about.
    """
    values = {f"P{i}": 6.0 for i in range(15)}
    values.update(sells or {"Gabriel": 8.0, "Semenyo": 8.5, "Out": 6.5,
                            "Enzo": 6.5, "A": 6.0, "B": 6.0, "Asset": 8.0,
                            "Owned": 6.0, "Settled": 7.0})
    return st.SquadState(bank=bank, free_transfers=free_transfers, event=4,
                         squad_size=15, selling_values=values,
                         purchase_values=values, selling_basis="conservative")


def move(out="Out", into="In", out_club="CHE", in_club="LIV", position="MID",
         selling=8.0, buying=6.5, out_5gw=18.0, in_5gw=27.0, **kw):
    made = st.Move(out, into, out_club=out_club, in_club=in_club,
                   position=position, selling_value=selling, buy_price=buying,
                   out_5gw=out_5gw, in_5gw=in_5gw, **kw)
    return made


def inputs(plan, sides, roll_net=1.6, **kw):
    margin = kw.pop("margin", round(plan.net_5gw - roll_net, 2))
    return tb.TransferBriefInputs(
        plan=plan, sides=sides, roll_net=roll_net, margin=margin,
        free_transfers=kw.pop("free_transfers", 1),
        bank_before=kw.pop("bank_before", 0.5), gameweek=4, **kw)


def upgrade_brief(**kw):
    """A clean upgrade: an insecure player out, a secure one in."""
    out = side("Enzo", outlook="50-50", minutes="30-75 minutes", urgency=52.0,
               hold=30.0, five=18.0)
    into = side("Szoboszlai", club="LIV", five=27.0, fixtures=EASY,
                set_pieces=True)
    swap = move("Enzo", "Szoboszlai", out_urgency=52.0, out_hold=30.0,
                out_minutes="Significant concern", in_minutes="Very secure",
                confidence="High")
    swap.reasons = [
        st.Reason("has started every league game", "Szoboszlai",
                  kind=st.FACT, direction="buy"),
        st.Reason("was withdrawn at half time", "Enzo", kind=st.FACT,
                  direction="sell")]
    plan = st._plan("single", [swap], state())
    return tb.build(inputs(plan, [(out, into)], **kw))


# --- every section is present and says something ------------------------

SECTIONS = ("why_move", "case_for", "case_against", "why_out", "why_in",
            "why_now", "why_not_roll", "horizon", "verdict")


def test_a_recommended_move_answers_every_section():
    brief = upgrade_brief()
    for section in SECTIONS:
        text = getattr(brief, section)
        assert text and len(text.split()) >= 8, f"{section} is thin: {text!r}"


def test_rolling_answers_every_section_that_applies():
    brief = tb.build(inputs(st.roll_plan(state()), []))
    for section in ("why_move", "case_for", "case_against", "why_now",
                    "why_not_roll", "horizon", "verdict"):
        assert getattr(brief, section), f"{section} is empty when rolling"
    assert brief.verdict_label == tb.ROLL


def test_the_verdict_is_a_label_a_manager_can_act_on():
    labels = {tb.MAKE_THE_MOVE, tb.ROLL, tb.HOLD_A_WEEK, tb.WATCHLIST,
              tb.CONDITIONAL, tb.NOT_WORTH_A_HIT}
    assert upgrade_brief().verdict_label in labels


# --- the hit is central, not an annotation ------------------------------

def test_a_hit_appears_in_the_headline_arithmetic():
    first = move("A", "X", out_5gw=20.0, in_5gw=23.0)
    second = move("B", "Y", out_5gw=20.0, in_5gw=23.2)
    plan = st._plan("package", [first, second], state(bank=1.0))
    brief = tb.build(inputs(plan, [(side("A"), side("X")),
                                   (side("B"), side("Y"))]))
    assert plan.hit == 4.0
    assert "4-point hit" in brief.arithmetic
    assert f"{plan.gross_5gw:+.1f}" in brief.arithmetic
    assert f"{plan.net_5gw:+.1f}" in brief.arithmetic


def test_a_hit_that_does_not_clear_rolling_is_refused():
    """The user's own worked example: +6.2 gross, -4, +2.2 net, only +0.6
    against rolling. Not enough to break a settled pairing for."""
    first = move("Gabriel", "Calafiori", out_club="ARS", in_club="ARS",
                 position="DEF", out_5gw=21.4, in_5gw=22.4)
    second = move("Semenyo", "Saka", out_club="MCI", in_club="ARS",
                  out_5gw=25.0, in_5gw=30.2)
    plan = st._plan("package", [first, second], state(bank=0.0))
    assert plan.affordable, "the fixture must be affordable to test the hit"
    brief = tb.build(inputs(
        plan, [(side("Gabriel", "ARS", "DEF", 8.0), side("Calafiori", "ARS", "DEF", 6.5)),
               (side("Semenyo", "MCI"), side("Saka", "ARS", price=10.0))]))
    assert brief.verdict_label == tb.NOT_WORTH_A_HIT
    assert "4-point hit" in brief.verdict
    assert "against simply rolling" in brief.verdict


def test_a_package_is_argued_as_one_decision_covering_both_legs():
    first = move("A", "X", out_5gw=20.0, in_5gw=26.0)
    second = move("B", "Y", out_5gw=20.0, in_5gw=27.0)
    plan = st._plan("package", [first, second], state(bank=2.0))
    brief = tb.build(inputs(plan, [(side("A"), side("X")),
                                   (side("B"), side("Y"))]))
    for name in ("A", "B", "X", "Y"):
        assert name in brief.why_out + brief.why_in, f"{name} is not argued"
    assert "one decision rather than two" in brief.why_move


# --- why THIS player out ------------------------------------------------

def test_why_out_compares_him_with_the_other_realistic_sales():
    brief = upgrade_brief(other_sales=[
        ("Semenyo", 8.0, "Strong hold", "Very likely to start"),
        ("Mitchell", 22.0, "Hold", "Likely to start")])
    assert "Semenyo" in brief.why_out
    assert "Enzo" in brief.why_out


def test_selling_the_wrong_man_fails_the_trust_test():
    """If a clearly more sellable player exists, the move is selling the
    wrong one and must not be recommended."""
    out = side("Semenyo", urgency=8.0, hold=70.0, five=25.0)
    into = side("Saka", club="ARS", price=10.0, five=28.0, fixtures=EASY,
                penalties=True)
    swap = move("Semenyo", "Saka", out_5gw=25.0, in_5gw=28.0,
                out_urgency=8.0, out_hold=70.0)
    plan = st._plan("single", [swap], state(bank=1.6))
    brief = tb.build(inputs(plan, [(out, into)], other_sales=[
        ("Mitchell", 55.0, "Possible sell", "50-50")]))
    assert not brief.trusted
    failed = [q for q, ok, _ in brief.trust if not ok]
    assert "Is he the right player to sell?" in failed
    assert brief.verdict_label == tb.WATCHLIST


def test_selling_the_right_man_passes_that_check():
    brief = upgrade_brief(other_sales=[
        ("Semenyo", 8.0, "Strong hold", "Very likely to start")])
    assert dict((q, ok) for q, ok, _ in brief.trust)[
        "Is he the right player to sell?"]


# --- why THIS player in -------------------------------------------------

def test_why_in_names_the_alternative_target_and_what_happened_to_it():
    brief = upgrade_brief(other_targets=[
        ("Palmer", 1.2, "corroboration: nothing published argues against him")])
    assert "Palmer" in brief.why_in
    assert "refused" in brief.why_in


def test_a_same_club_swap_says_the_fixtures_cannot_separate_them():
    out = side("Gabriel", "ARS", "DEF", 8.0, urgency=5.0, hold=60.0,
               five=21.4, fixtures=EASY)
    into = side("Calafiori", "ARS", "DEF", 6.5, outlook="Likely to start",
                minutes="60-90 minutes", five=22.0, fixtures=EASY)
    swap = move("Gabriel", "Calafiori", out_club="ARS", in_club="ARS",
                position="DEF", selling=8.0, buying=6.5, out_5gw=21.4,
                in_5gw=22.0, out_urgency=5.0, out_hold=60.0)
    plan = st._plan("single", [swap], state())
    brief = tb.build(inputs(plan, [(out, into)]))
    assert "same club" in brief.why_in or "share every fixture" in brief.why_in
    assert "budget release" in brief.why_in or "not a direct upgrade" in brief.why_in


# --- why now, and why not roll ------------------------------------------

FLAT = [("EVE (H)", 3.0), ("FUL (A)", 3.0), ("BHA (H)", 3.0),
        ("WOL (A)", 3.0), ("CRY (H)", 3.0)]


def test_no_urgency_is_stated_as_no_urgency():
    """A move whose gain is spread evenly and whose outgoing player is
    fine has no reason to happen this week rather than next."""
    out = side("Settled", urgency=12.0, five=22.0, fixtures=FLAT)
    into = side("Target", club="LIV", five=25.0, fixtures=FLAT)
    swap = move("Settled", "Target", out_5gw=22.0, in_5gw=25.0)
    plan = st._plan("single", [swap], state())
    brief = tb.build(inputs(plan, [(out, into)]))
    assert "no urgency" in brief.why_now.lower()


def test_a_minutes_problem_is_a_reason_to_move_now():
    assert "another week" in upgrade_brief().why_now


def test_why_not_roll_prices_the_flexibility_being_given_up():
    brief = upgrade_brief()
    assert "+1.6" in brief.why_not_roll
    assert f"{brief_net(brief):+.1f}" in brief.why_not_roll


def brief_net(brief):
    import re
    found = re.search(r"scores ([+-]\d+\.\d)", brief.why_not_roll)
    return float(found.group(1)) if found else 0.0


def test_why_not_roll_does_not_advocate_a_move_the_verdict_refuses():
    """"That is enough to spend the transfer on" under a verdict of
    WATCHLIST is the page arguing with itself in two sections."""
    out = side("Semenyo", urgency=8.0, hold=70.0, five=25.0)
    into = side("Saka", club="ARS", price=10.0, five=28.0, fixtures=EASY)
    swap = move("Semenyo", "Saka", out_5gw=25.0, in_5gw=28.0,
                out_urgency=8.0, out_hold=70.0)
    plan = st._plan("single", [swap], state(bank=1.6))
    brief = tb.build(inputs(plan, [(out, into)], other_sales=[
        ("Mitchell", 55.0, "Possible sell", "50-50")]))
    assert brief.verdict_label != tb.MAKE_THE_MOVE
    assert "enough to spend the transfer on" not in brief.why_not_roll


# --- there is always an argument against --------------------------------

def test_every_brief_contains_a_real_case_against_itself():
    for brief in (upgrade_brief(), tb.build(inputs(st.roll_plan(state()), []))):
        assert len(brief.case_against.split()) >= 12, brief.case_against


def test_selling_a_strong_hold_is_named_as_the_biggest_downside():
    out = side("Asset", urgency=8.0, hold=72.0, five=25.0)
    into = side("Shiny", club="LIV", five=28.0, fixtures=EASY)
    swap = move("Asset", "Shiny", out_5gw=25.0, in_5gw=28.0,
                out_urgency=8.0, out_hold=72.0)
    plan = st._plan("single", [swap], state())
    brief = tb.build(inputs(plan, [(out, into)]))
    assert "not a problem" in brief.case_against
    assert "hold strength" in brief.case_against


def test_an_unconfirmed_incoming_starter_is_named_as_a_risk():
    out = side("Owned", urgency=40.0, five=20.0)
    into = side("Punt", club="LIV", outlook="50-50", minutes="30-75 minutes",
                five=26.0, fixtures=EASY)
    swap = move("Owned", "Punt", out_5gw=20.0, in_5gw=26.0, out_urgency=40.0)
    plan = st._plan("single", [swap], state())
    brief = tb.build(inputs(plan, [(out, into)]))
    assert "assumes minutes" in brief.case_against
    assert brief.verdict_label == tb.CONDITIONAL
    assert brief.confidence != "High"


# --- confidence ---------------------------------------------------------

def test_confidence_is_never_high_on_an_unconfirmed_starting_place():
    out = side("Owned", urgency=40.0, five=20.0)
    for outlook in ("50-50", "Likely bench", "Very unlikely to start"):
        into = side("Punt", club="LIV", outlook=outlook, five=26.0)
        swap = move("Owned", "Punt", out_5gw=20.0, in_5gw=26.0)
        plan = st._plan("single", [swap], state())
        brief = tb.build(inputs(plan, [(out, into)]))
        assert brief.confidence != "High", outlook


def test_a_new_signing_coming_in_is_not_high_confidence():
    out = side("Owned", urgency=40.0, five=20.0)
    into = side("Newcomer", club="LIV", five=26.0, new_club="joined this week")
    swap = move("Owned", "Newcomer", out_5gw=20.0, in_5gw=26.0)
    plan = st._plan("single", [swap], state())
    assert tb.build(inputs(plan, [(out, into)])).confidence != "High"


# --- the horizon and the future ----------------------------------------

def test_the_horizon_covers_three_and_five_gameweeks():
    brief = upgrade_brief()
    assert "next three" in brief.horizon
    assert "Across five" in brief.horizon


def test_a_run_that_hardens_warns_about_a_reversal():
    out = side("Owned", urgency=40.0, five=20.0)
    into = side("Shortterm", club="LIV", five=26.0, fixtures=[
        ("BUR (H)", 2.0), ("SHU (H)", 2.0), ("MCI (A)", 4.6),
        ("LIV (A)", 4.4), ("ARS (A)", 4.2)])
    swap = move("Owned", "Shortterm", out_5gw=20.0, in_5gw=26.0)
    plan = st._plan("single", [swap], state())
    brief = tb.build(inputs(plan, [(out, into)]))
    assert "revisiting" in brief.horizon or "reversing" in brief.case_against


def test_a_rejected_move_gets_two_sentences_not_an_essay():
    swap = move("A", "B", out_5gw=20.0, in_5gw=21.0)
    plan = st.reject(st._plan("single", [swap], state()))
    note = tb.rejected_note(plan)
    assert plan.rejected
    assert 5 <= len(note.split()) <= 60, note


def test_a_watchlist_entry_is_a_condition_not_a_prediction():
    swap = move("A", "B", out_5gw=20.0, in_5gw=21.0)
    plan = st.reject(st._plan("single", [swap], state()))
    note = tb.watchlist_note(plan, side("B", outlook="50-50"))
    assert "WHY WE ARE WAITING" in note and "TRIGGERS" in note
    assert "will" not in note.split("TRIGGERS")[0].lower()


# --- the trust test -----------------------------------------------------

def test_the_trust_test_asks_ten_questions():
    assert len(upgrade_brief().trust) == 10


def test_a_clean_upgrade_passes_all_ten():
    brief = upgrade_brief(other_sales=[
        ("Semenyo", 8.0, "Strong hold", "Very likely to start")])
    assert brief.trusted, [q for q, ok, _ in brief.trust if not ok]


def test_a_move_with_no_published_evidence_fails_the_evidence_question():
    out = side("Owned", urgency=45.0, outlook="50-50", five=20.0)
    into = side("Target", club="LIV", five=26.0, fixtures=EASY)
    swap = move("Owned", "Target", out_5gw=20.0, in_5gw=26.0, out_urgency=45.0)
    plan = st._plan("single", [swap], state())
    brief = tb.build(inputs(plan, [(out, into)]))
    failed = [q for q, ok, _ in brief.trust if not ok]
    assert "Does the reasoning use actual evidence?" in failed


# --- defects the live regression run exposed ----------------------------

def test_an_unaffordable_move_is_refused_before_anything_else_is_argued():
    """It was printed with a negative bank and a verdict about team news."""
    out = side("Owned", price=5.0, five=20.0)
    into = side("Expensive", club="LIV", price=12.0, five=28.0)
    swap = move("Owned", "Expensive", selling=5.0, buying=12.0,
                out_5gw=20.0, in_5gw=28.0)
    plan = st._plan("single", [swap], state(bank=0.0, sells={"Owned": 5.0}))
    brief = tb.build(inputs(plan, [(out, into)]))
    assert not plan.affordable
    assert "cannot be afforded" in brief.verdict
    assert "UNAFFORDABLE" in brief.arithmetic
    assert "cannot be afforded" in brief.case_against


def test_a_sale_is_compared_with_a_player_in_the_same_position():
    """A midfielder was measured against the backup goalkeeper, twice."""
    brief = upgrade_brief(other_sales=[
        ("Backup keeper", 50.0, "Possible sell", "Likely bench", "GKP"),
        ("Another mid", 30.0, "Monitor", "Likely to start", "MID")])
    assert "Another mid" in brief.why_out
    assert "Backup keeper" not in brief.why_out


def test_the_same_sentence_is_not_repeated_for_two_alternatives():
    brief = upgrade_brief(other_sales=[
        ("First", 60.0, "Possible sell", "50-50", "MID"),
        ("Second", 58.0, "Possible sell", "50-50", "MID")])
    sentences = [part.strip() for part in brief.why_out.split(". ") if part]
    assert len(sentences) == len(set(sentences)), brief.why_out


def test_a_player_with_no_fixture_list_says_so_rather_than_printing_dashes():
    blank = side("Unknown", fixtures=[("—", 3.0)] * 4)
    assert "no fixture list" in blank.labels()


def test_selling_out_of_position_does_not_block_the_sale_justification():
    """A more sellable GOALKEEPER is not a reason to refuse a midfield
    upgrade — you cannot buy a midfielder with a goalkeeper's money."""
    brief = upgrade_brief(other_sales=[
        ("Backup keeper", 70.0, "Strong sell", "Likely bench", "GKP")])
    assert dict((q, ok) for q, ok, _ in brief.trust)[
        "Is he the right player to sell?"]

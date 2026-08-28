"""Every owned player gets a real assessment — never an empty card.

The behaviour being deleted: a player nobody had written an FPL article
about got "no researched reasoning" and the page moved on. That is a
statement about the FPL blogosphere, not about the footballer.

The reframing these tests protect: football news IS Fantasy news. An
omission from a squad, a manager declining to commit, a bid, a full-back
suddenly at left wing — each changes an expected-minutes picture without
a single FPL writer mentioning it, and each must reach the page.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.analysis import consensus, dossier
from fpl_assistant.research import completeness


def _row(**kw):
    base = {
        "id": 1, "web_name": "Enzo", "team_short_name": "CHE", "position": "MID",
        "price": 6.5, "selected_by_percent": 5.0, "status": "a",
    }
    base.update(kw)
    return pd.Series(base)


def _frame(events=None, transfer=None, **kw):
    frame = pd.DataFrame([dict(_row(**kw))])
    frame["player_events"] = consensus._pack(events or [])
    if transfer:
        frame["transfer_status"] = transfer.get("status")
        frame["transfer_detail"] = transfer.get("detail")
    return frame


# --- no empty profiles ---------------------------------------------------

def test_a_player_nobody_has_written_about_still_gets_every_section():
    """The core rule. Thin evidence changes what the sections say, never
    whether they exist."""
    d = dossier.build(_frame().iloc[0], gameweek=2, fixtures=[])

    assert d.this_gameweek
    assert d.why_in_squad
    assert d.case_for_keeping
    assert d.case_for_selling
    assert d.latest_developments
    assert d.expert_view
    assert d.risks
    assert d.verdict in dossier.VERDICTS
    assert d.confidence in ("High", "Medium", "Low")


def test_thin_evidence_is_named_as_a_risk_not_treated_as_a_clean_bill():
    d = dossier.build(_frame().iloc[0], gameweek=2, fixtures=[])

    assert d.evidence_thin
    assert "we know little about him" in d.risks
    assert d.confidence == "Low"


def test_limited_fpl_coverage_produces_an_escalation_note_not_an_apology():
    frame = _frame()
    frame["research_depth"] = "club news"
    d = dossier.build(frame.iloc[0], gameweek=2, fixtures=[])

    note = d.escalation_note()
    assert "widened to current club news" in note
    assert "no write-up" not in note.lower()


# --- the Enzo Fernández problem, worked end to end ----------------------

def test_the_enzo_case_produces_a_minutes_warning_without_claiming_he_is_out():
    """The permanent worked example.

    Omitted from the squad, active transfer talks, manager not committing.
    None of that is an FPL article and all of it is FPL information — but
    the conclusion must be "minutes risk", never "he definitely won't play".
    """
    frame = _frame(
        events=[
            {"kind": "not in squad", "detail": "Left out of the matchday squad at Fulham",
             "source": "Chelsea", "when": "22 Aug"},
            {"kind": "manager quote",
             "detail": "Rosenior called it a selection decision and did not rule him out of the next game",
             "source": "Chelsea"},
        ],
        transfer={"status": "Active talks", "detail": "Reported interest with talks under way."},
    )
    d = dossier.build(frame.iloc[0], gameweek=2, fixtures=[])

    assert d.minutes_outlook in ("Significant concern", "Major doubt")
    assert d.status == "Transfer risk"
    assert d.verdict == "MONITOR"           # not SELL — nothing is confirmed
    assert "left out of the most recent matchday squad" in d.minutes_reasons
    assert "Active talks" in d.case_for_selling
    # And it must NOT overclaim.
    assert "will not play" not in d.this_gameweek.lower()
    assert "definitely" not in d.this_gameweek.lower()


def test_an_omission_alone_raises_the_minutes_concern():
    frame = _frame(events=[{"kind": "not in squad", "detail": "Not in the 20", "source": "Chelsea"}])
    d = dossier.build(frame.iloc[0], gameweek=2, fixtures=[])
    assert d.minutes_index >= 3


def test_a_new_signing_in_his_position_counts_against_his_minutes():
    frame = _frame(events=[{"kind": "new signing", "detail": "Club signed a striker", "source": "GOAL"}])
    d = dossier.build(frame.iloc[0], gameweek=2, fixtures=[])
    assert d.minutes_index >= 2
    assert "new competition for his place" in d.minutes_reasons


def test_current_news_overrides_the_models_minutes_call():
    """A statistical minutes estimate summarises the past. An omission is
    the present, and the present wins."""
    frame = _frame(events=[{"kind": "injury", "detail": "Hamstring", "source": "Premier Injuries"}])
    frame["predicted_start"] = "nailed"
    d = dossier.build(frame.iloc[0], gameweek=2, fixtures=[])

    assert d.minutes_outlook == "Major doubt"
    assert d.verdict == "SELL"


# --- transfer grading ----------------------------------------------------

def test_transfer_status_is_graded_not_believed_or_dismissed():
    quiet = dossier.build(
        _frame(transfer={"status": "Low-level rumour", "detail": "x"}).iloc[0], 2, fixtures=[])
    serious = dossier.build(
        _frame(transfer={"status": "Bid made", "detail": "x"}).iloc[0], 2, fixtures=[])

    # A low-level rumour alone must not push him toward the exit — but it
    # also must not earn him a "Secure" label he has no evidence for.
    assert quiet.minutes_outlook == dossier.MINUTES_UNKNOWN
    assert quiet.verdict != "SELL"
    assert quiet.sell_urgency <= 2
    assert serious.verdict == "SELL"
    assert serious.sell_urgency == 5


def test_an_unrecognised_transfer_status_falls_back_to_none():
    frame = _frame(transfer={"status": "definitely leaving probably", "detail": "x"})
    d = dossier.build(frame.iloc[0], 2, fixtures=[])
    assert d.transfer_status == "None"


# --- fact / inference / unconfirmed --------------------------------------

def test_the_three_kinds_of_statement_are_kept_apart():
    """Collapsing them is how speculation becomes fact."""
    assert dossier.Claim("He was omitted", dossier.FACT).display == "He was omitted"
    assert dossier.Claim("Minutes less secure", dossier.INFERENCE).display.startswith("*Inference:*")
    assert dossier.Claim("A bid is expected", dossier.UNCONFIRMED).display.startswith("*Unconfirmed:*")


def test_major_events_sort_above_routine_ones():
    events = dossier.parse_events([
        {"kind": "started", "detail": "played 90"},
        {"kind": "transfer bid", "detail": "bid received"},
    ])
    assert events[0].kind == "transfer bid"
    assert events[0].major and not events[1].major


def test_unknown_event_kinds_are_dropped_rather_than_shown():
    assert dossier.parse_events([{"kind": "vibes", "detail": "x"}]) == []


# --- completeness gate ---------------------------------------------------

def _rich_dossier():
    frame = _frame(
        events=[{"kind": "started", "detail": "90 mins", "source": "Chelsea"},
                {"kind": "manager quote", "detail": "praised him", "source": "Chelsea"}],
        transfer={"status": "None", "detail": ""},
    )
    frame["consensus_for"] = consensus._pack([{"point": "He is on penalties", "source": "RotoWire"}])
    frame["consensus_against"] = consensus._pack([{"point": "Tough run", "source": "GOAL"}])
    frame["role_note"] = "the No.10"
    frame["set_pieces"] = "penalties"
    frame["predicted_start"] = "nailed"
    frame["prior_seasons"] = "2025/26: 102 pts"
    frame["record_vs_opponent"] = "Two goals in three"
    d = dossier.build(frame.iloc[0], 2, fixtures=[], fixture_run=["GW2 BHA (H)", "GW3 EVE (A)"],
                      starting=True)
    d.fixture = "home to BHA"
    return d


def test_a_well_researched_player_passes_the_completeness_gate():
    report = completeness.check([_rich_dossier()])
    assert report.ready, report.players[0].missing
    assert report.players[0].score >= completeness.PASS_THRESHOLD


def test_a_bare_player_fails_and_is_named():
    bare = dossier.build(_frame(web_name="Anon").iloc[0], 2, fixtures=[])
    report = completeness.check([bare])

    assert not report.ready
    assert "Anon" in report.headline
    assert "Still thin on" in report.headline


def test_the_gate_names_the_searches_that_would_close_the_gaps():
    """A named next step is the difference between escalating and stopping."""
    bare = dossier.build(_frame(web_name="Anon").iloc[0], 2, fixtures=[])
    report = completeness.check([bare])
    queries = completeness.next_searches(report.players[0], "Anon")

    assert queries
    assert any("transfer" in q for q in queries)
    assert any("manager press conference" in q for q in queries)


def test_the_report_lists_the_worst_researched_first():
    report = completeness.check([_rich_dossier(),
                                 dossier.build(_frame(id=2, web_name="Anon").iloc[0], 2, fixtures=[])])
    assert report.worst_first[0].name == "Anon"


def test_every_check_has_a_label_and_a_test():
    for key, label, test in completeness.CHECKS:
        assert key and label and callable(test)
    assert len(completeness.CHECKS) == 14


def test_a_penalty_appointment_is_a_reason_to_keep_not_to_sell():
    """Caught when real data first ran through the pipeline.

    "Major" was being used to mean both "surface this prominently" and
    "this argues for selling", so a penalty appointment — the single best
    thing that can happen to a midfielder — appeared in the case for
    selling him. Importance and direction are different axes.
    """
    frame = _frame(events=[
        {"kind": "penalty change", "detail": "Now first-choice penalty taker", "source": "FFS"},
        {"kind": "set-piece change", "detail": "Took every corner and free-kick", "source": "FFS"},
    ])
    d = dossier.build(frame.iloc[0], 2, fixtures=[], starting=True)

    assert "PENALTY CHANGE" in d.case_for_keeping
    assert "PENALTY CHANGE" not in d.case_for_selling
    assert d.verdict == "KEEP"


def test_a_bid_is_a_reason_to_sell():
    frame = _frame(events=[
        {"kind": "club open to sale", "detail": "Bid accepted", "source": "GOAL"},
    ])
    d = dossier.build(frame.iloc[0], 2, fixtures=[], starting=True)

    assert "CLUB OPEN TO SALE" in d.case_for_selling
    assert "CLUB OPEN TO SALE" not in d.case_for_keeping


def test_importance_and_direction_are_separate_axes():
    assert "penalty change" in dossier.MAJOR_EVENTS
    assert "penalty change" not in dossier.NEGATIVE_EVENTS
    assert "injury" in dossier.MAJOR_EVENTS and "injury" in dossier.NEGATIVE_EVENTS


def test_the_shipped_research_carries_structured_events():
    """The schema has to be in use, not merely supported."""
    import json
    from pathlib import Path

    data = json.loads(
        (Path(__file__).resolve().parent.parent / "data" / "consensus" / "gw2.json").read_text()
    )
    with_events = [p for p in data["players"] if p.get("events")]
    assert len(with_events) >= 5

    for player in with_events:
        assert player.get("transfer", {}).get("status") in dossier.TRANSFER_LEVELS
        for event in player["events"]:
            assert event["kind"] in dossier.EVENT_TYPES, event["kind"]
            assert event.get("source"), f"{player['name']}: unattributed event"


def test_the_watkins_transfer_produces_a_sell_from_football_news_alone():
    """No FPL article said "sell Watkins". The football news did."""
    import json
    from pathlib import Path

    data = json.loads(
        (Path(__file__).resolve().parent.parent / "data" / "consensus" / "gw2.json").read_text()
    )
    watkins = next(p for p in data["players"] if p["name"] == "Watkins")

    assert watkins["transfer"]["status"] == "Advanced"
    assert any(e["kind"] == "club open to sale" for e in watkins["events"])
    assert watkins["research_depth"] == "football news"


# --- security must be earned, never assumed ------------------------------

def test_an_unresearched_player_is_never_called_a_secure_starter():
    """The Enzo Fernández bug, at its root.

    The first version started every player at "Secure" and escalated only
    on contradicting evidence, so a player nobody had researched came out
    as SECURE STARTER / MINUTES SECURE with an EMPTY reasons list. Absence
    of evidence was reading as evidence of security — which is how the
    page called a man a secure starter while his transfer was being
    negotiated and he had just been left out of a cup squad.
    """
    d = dossier.build(_frame(web_name="Nobody").iloc[0], 2, fixtures=[], starting=True)

    assert d.minutes_outlook == dossier.MINUTES_UNKNOWN
    assert d.status == "Not yet researched"
    assert d.minutes_reasons, "an unchecked player must still say WHY it is unchecked"
    assert "unchecked rather than confirmed" in d.minutes_reasons[0]
    assert "Secure" not in d.status


def test_security_is_earned_by_positive_evidence():
    nailed = _frame()
    nailed["predicted_start"] = "nailed"
    assert dossier.build(nailed.iloc[0], 2, fixtures=[]).minutes_outlook == "Very secure"

    started = _frame(events=[{"kind": "started", "detail": "90 mins", "source": "Chelsea"}])
    assert dossier.build(started.iloc[0], 2, fixtures=[]).minutes_outlook == "Secure"


def test_an_unchecked_player_never_claims_nothing_specific_against_him():
    d = dossier.build(_frame().iloc[0], 2, fixtures=[], starting=True)
    assert "minutes have not been confirmed" in d.case_for_selling
    assert d.case_for_selling != "Nothing specific."


def test_every_minutes_call_carries_a_reason():
    """A label with no reason behind it is the thing that went wrong."""
    for events, predicted in (([], ""), ([], "nailed"),
                              ([{"kind": "not in squad", "detail": "x", "source": "y"}], "nailed")):
        frame = _frame(events=events)
        if predicted:
            frame["predicted_start"] = predicted
        d = dossier.build(frame.iloc[0], 2, fixtures=[])
        assert d.minutes_reasons, f"no reason for {d.minutes_outlook}"


# --- recency conflict ----------------------------------------------------

def test_a_stored_nailed_label_against_fresh_bad_news_is_flagged():
    frame = _frame(events=[
        {"kind": "not in squad", "detail": "Left out of the cup squad", "source": "ESPN"},
    ])
    frame["predicted_start"] = "nailed"
    d = dossier.build(frame.iloc[0], 2, fixtures=[])

    conflict = d.recency_conflict
    assert "Recency conflict" in conflict
    assert "Fresh evidence wins" in conflict
    # And the fresh evidence actually won.
    assert d.minutes_outlook == "Significant concern"


def test_no_conflict_is_reported_when_the_evidence_agrees():
    frame = _frame(events=[{"kind": "started", "detail": "90", "source": "Chelsea"}])
    frame["predicted_start"] = "nailed"
    assert dossier.build(frame.iloc[0], 2, fixtures=[]).recency_conflict == ""


# --- sell urgency, and selling the right player --------------------------

def test_the_enzo_profile_outranks_a_settled_starter_for_selling():
    """The decision the engine got backwards.

    Selling a settled starter in an elite attack to fund another
    midfielder, while keeping a player who was substituted on, then
    omitted from a squad, with active transfer interest, is exactly the
    wrong way round.
    """
    enzo = _frame(
        id=1, web_name="Enzo",
        events=[
            {"kind": "benched", "detail": "Came on as a sub in the opener", "source": "ESPN"},
            {"kind": "not in squad", "detail": "Omitted from the cup squad", "source": "ESPN"},
        ],
        transfer={"status": "Credible interest", "detail": "City interested"},
    )
    settled = _frame(id=2, web_name="Semenyo",
                     events=[{"kind": "started", "detail": "Starts wide left", "source": "MCFC"}])
    settled["predicted_start"] = "nailed"
    settled["set_pieces"] = "corners"

    a = dossier.build(enzo.iloc[0], 2, fixtures=[], starting=True)
    b = dossier.build(settled.iloc[0], 2, fixtures=[], starting=True)
    ranking = dossier.rank_by_sell_urgency([a, b])

    assert a.sell_urgency >= 4
    assert b.sell_urgency <= 1
    assert ranking.ordered[0].name == "Enzo"
    assert b in ranking.protected


def test_selling_the_wrong_player_is_challenged_in_writing():
    """If the engine cannot answer "why him and not the other one?", the
    transfer should not survive."""
    enzo = _frame(id=1, web_name="Enzo",
                  events=[{"kind": "not in squad", "detail": "Omitted", "source": "ESPN"}])
    settled = _frame(id=2, web_name="Semenyo",
                     events=[{"kind": "started", "detail": "Starts", "source": "MCFC"}])
    settled["predicted_start"] = "nailed"
    settled["set_pieces"] = "corners"

    ranking = dossier.rank_by_sell_urgency([
        dossier.build(enzo.iloc[0], 2, fixtures=[], starting=True),
        dossier.build(settled.iloc[0], 2, fixtures=[], starting=True),
    ])
    challenge = ranking.why_this_one(2)     # selling Semenyo

    assert "NOT the most urgent sale" in challenge
    assert "Enzo" in challenge
    assert "wrong move" in challenge


def test_selling_the_most_urgent_player_is_justified_against_the_runner_up():
    enzo = _frame(id=1, web_name="Enzo",
                  events=[{"kind": "not in squad", "detail": "Omitted", "source": "ESPN"}])
    settled = _frame(id=2, web_name="Semenyo",
                     events=[{"kind": "started", "detail": "Starts", "source": "MCFC"}])
    settled["predicted_start"] = "nailed"

    ranking = dossier.rank_by_sell_urgency([
        dossier.build(enzo.iloc[0], 2, fixtures=[], starting=True),
        dossier.build(settled.iloc[0], 2, fixtures=[], starting=True),
    ])
    justification = ranking.why_this_one(1)

    assert "most urgent sale" in justification
    assert "Semenyo" in justification


def test_a_strong_asset_is_protected_from_drifting_up_the_sell_list():
    """Starting, no concern, on set pieces — the bar for selling him is
    high, not average."""
    frame = _frame(events=[{"kind": "started", "detail": "90", "source": "MCFC"}])
    frame["predicted_start"] = "nailed"
    frame["set_pieces"] = "corners and free-kicks"
    frame["consensus_against"] = consensus._pack([{"point": "Tough run", "source": "GOAL"}])

    d = dossier.build(frame.iloc[0], 2, fixtures=[], starting=True)
    assert d.sell_urgency <= 1


def test_the_shipped_research_ranks_enzo_above_semenyo():
    """Against the real committed file, not a fixture."""
    import pandas as _pd

    frame = _pd.DataFrame([
        {"id": 1, "web_name": "Enzo", "team_short_name": "CHE", "position": "MID",
         "price": 7.0, "team": 1, "selected_by_percent": 6.0, "status": "a"},
        {"id": 2, "web_name": "Semenyo", "team_short_name": "MCI", "position": "MID",
         "price": 8.0, "team": 2, "selected_by_percent": 18.0, "status": "a"},
    ]).set_index("id", drop=False)
    annotated = consensus.annotate(frame, 2)

    enzo = dossier.build(annotated.loc[1], 2, starting=True)
    semenyo = dossier.build(annotated.loc[2], 2, starting=True)

    assert enzo.sell_urgency > semenyo.sell_urgency
    assert enzo.status != "Secure starter"
    assert semenyo.status == "Secure starter"
    assert "Omitted from the Carabao Cup squad" in enzo.case_for_selling

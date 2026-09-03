"""Evidence must be about the player before it can say anything about him.

Every test here is a real failure taken from the live homepage:

  * "Foden and Cherki are the City players to triple up on" became a
    reason to SELL SEMENYO — an article silent on Semenyo read as an
    argument against him.
  * "Chelsea have scored seven" became a reason to sell Gabriel.
  * A note about Tzolakis being heavily bought appeared as a RISK TO RAYA.
  * João Pedro's news appeared inside Raya's card.

None of these are layout problems. They are what happens when there is no
step between an article sentence and a conclusion.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.analysis import player_facts as pf
from fpl_assistant.analysis import writeup


def quote(text, source="Fantasy Football Scout"):
    return {"text": text, "source": source, "url": "https://x.com/a", "published": ""}


# --- the relevance gate --------------------------------------------------

def test_an_article_about_other_players_is_not_evidence_against_this_one():
    """The Semenyo failure, exactly."""
    claim = pf.classify(
        "Foden and Cherki are the Manchester City players to triple up on this week.",
        "Semenyo", "MCI")
    assert claim is None or not claim.player_named
    if claim:
        assert not (set(claim.buckets) & pf.SELL_SUPPORT), claim.buckets


def test_a_club_scoring_record_is_not_a_reason_to_sell_a_defender():
    """"Chelsea have scored seven" became a reason to sell Gabriel."""
    claim = pf.classify("Chelsea have scored seven goals in two matches.",
                        "Gabriel", "ARS")
    assert claim is None, claim


def test_another_players_transfer_traffic_is_not_a_risk_to_this_one():
    """A note about Tzolakis being heavily bought appeared as a risk to Raya."""
    claim = pf.classify(
        "Tzolakis is the most transferred in goalkeeper this gameweek.",
        "Raya", "ARS")
    assert claim is None or not claim.player_named


def test_one_players_news_does_not_reach_another_players_card():
    facts = pf.build("Raya", "ARS", "GKP", 6.0, quotes=[
        quote("Joao Pedro has bagged a goal and an assist in both matches."),
    ])
    assert not [c for c in facts.claims if c.player_named]
    assert "Pedro" not in writeup.from_facts(facts)


def test_a_sentence_naming_the_player_is_kept():
    claim = pf.classify(
        "David Raya kept his fifth clean sheet and was named in the team of the week.",
        "Raya", "ARS")
    assert claim is not None and claim.player_named


def test_club_level_facts_are_allowed_but_only_into_club_buckets():
    """A clean-sheet outlook is a real fact about a defender's prospects.
    It may inform the fixture view; it may not become a claim he made."""
    claim = pf.classify(
        "Arsenal have the strongest clean sheet odds of the gameweek.",
        "Gabriel", "ARS")
    assert claim is not None
    assert not claim.player_named
    assert set(claim.buckets) <= pf.CLUB_LEVEL_BUCKETS


# --- conclusions need the right support ----------------------------------

def test_selling_requires_evidence_that_supports_selling():
    facts = pf.build("Semenyo", "MCI", "MID", 8.5, quotes=[
        quote("Foden and Cherki are the City players to triple up on."),
        quote("Manchester City host Coventry at the Etihad this weekend."),
    ])
    assert not facts.supports_sale()


def test_a_real_sell_signal_is_recognised():
    facts = pf.build("Semenyo", "MCI", "MID", 8.5, quotes=[
        quote("Semenyo was left out of the squad entirely for the cup tie."),
    ])
    assert facts.supports_sale()
    assert facts.recent_selection == pf.OMITTED


def test_the_expert_view_only_counts_advice_about_him():
    about_others = pf.build("Semenyo", "MCI", "MID", 8.5, quotes=[
        quote("Buy Cherki this week — he is the standout pickup."),
    ])
    assert about_others.expert_view == pf.LIMITED

    about_him = pf.build("Semenyo", "MCI", "MID", 8.5, quotes=[
        quote("Semenyo is a hold — there is no reason to sell him now."),
    ])
    assert about_him.expert_view == pf.HOLD


def test_claims_are_labelled_fact_statistic_or_opinion():
    """An inference must never be presented as something a journalist said."""
    stat = pf.classify("Haaland is averaging 0.85 xG per 90 this season.",
                       "Haaland", "MCI")
    opinion = pf.classify("Haaland is a clear buy for the coming run.",
                          "Haaland", "MCI")
    assert stat.kind == pf.STATISTICAL
    assert opinion.kind == pf.EXPERT


# --- the card must not contradict itself ---------------------------------

def test_minutes_label_and_prose_agree():
    """The homepage showed "MINUTES VERY SECURE" while the prose said they
    were unassessed."""
    facts = pf.build("Kayode", "BRE", "DEF", 4.6, expected_minutes="Unknown")
    text = writeup.from_facts(facts)
    assert "secure" not in text.lower()
    assert "settles his minutes" in text


def test_secure_minutes_read_as_secure():
    facts = pf.build("Raya", "ARS", "GKP", 6.0, expected_minutes="Very secure")
    assert "very secure" in writeup.from_facts(facts).lower()


def test_the_main_risk_is_a_risk_to_this_player():
    facts = pf.build("Raya", "ARS", "GKP", 6.0, expected_minutes="Very secure",
                     quotes=[quote("Tzolakis is the most transferred in goalkeeper.")])
    assert "Tzolakis" not in (facts.main_risk or "")


def test_the_write_up_stays_within_a_readable_length():
    facts = pf.build("Haaland", "MCI", "FWD", 15.5, expected_minutes="Very secure",
                     fixture="COV (H)", captain=True,
                     quotes=[quote(f"Haaland is a clear buy and takes the penalties. "
                                   f"Sentence {i}.") for i in range(20)])
    words = len(writeup.from_facts(facts).split())
    assert 15 <= words <= 120, words


def test_the_quality_check_catches_a_leaked_claim():
    facts = pf.build("Raya", "ARS", "GKP", 6.0)
    facts.claims.append(pf.Claim(text="Joao Pedro scored twice.", kind=pf.FACT,
                                 buckets=(pf.FORM,), player_named=False))
    problems = writeup.quality_check(facts)
    assert any("not about Raya" in p for p in problems)


def test_the_quality_check_catches_a_sale_with_no_case():
    facts = pf.build("Gabriel", "ARS", "DEF", 8.0)
    facts.verdict = pf.SELL_VERDICT
    assert any("no evidence" in p for p in writeup.quality_check(facts))


def test_an_unavailable_player_is_flagged_for_the_squad():
    facts = pf.build("Injured", "ARS", "DEF", 5.0, availability=pf.OUT)
    assert facts.verdict == pf.SELL_VERDICT
    assert "unavailable" in facts.main_risk

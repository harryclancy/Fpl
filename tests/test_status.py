"""The freshness layer, tested on the failure that caused it.

A player moved to Manchester City and the app went on showing START /
MINUTES SECURE / CONFIDENCE HIGH, because every one of those labels was
computed from a record he had built at Everton. These tests are written
against the RULES rather than against a named footballer, so a change of
squad cannot make them pass vacuously — the Ndiaye case is expressed as
"a player who has just changed clubs", which is what the code actually
reasons about.
"""
from datetime import datetime, timedelta, timezone

import pytest

from fpl_assistant.analysis import status as ST
from fpl_assistant.research import evidence as ev
from fpl_assistant.research import status_evidence as se
from fpl_assistant.research.collect import Article

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)

CITY_XI_BENCHING_HIM = (
    "Manchester City predicted XI (4-2-3-1): Ederson; Walker, Dias, Gvardiol, "
    "Ake; Rodri, Kovacic; Foden, Cherki, Semenyo; Haaland. "
    "Subs: Ortega, Stones, Newman, Grealish.")
CITY_XI_STARTING_HIM = (
    "Manchester City predicted XI (4-2-3-1): Ederson; Walker, Dias, Gvardiol, "
    "Ake; Rodri, Kovacic; Foden, Newman, Semenyo; Haaland. "
    "Subs: Ortega, Stones, Grealish.")


def article(title, body="", source="Sports Mole", domain="sportsmole.co.uk",
            hours_ago=6):
    return Article(title=title, url=f"https://{domain}/a", source=source,
                   domain=domain, body=body,
                   published=(NOW - timedelta(hours=hours_ago)).isoformat())


def assess(name="Newman", full="Alex Newman", club="MCI", articles=(), **kw):
    return ST.assess(name, club, list(articles),
                     ev.name_variants(name, full), ev.own_tokens(name, full),
                     ev.mentions_this_player, player_id=kw.pop("player_id", 1),
                     club_name=kw.pop("club_name", "Man City"),
                     price=kw.pop("price", 6.0), now=NOW, **kw)


def moved_this_week():
    return article("Alex Newman completed a move to Manchester City",
                   "Manchester City have completed the signing of Alex Newman "
                   "from Everton.", source="Sky Sports",
                   domain="skysports.com", hours_ago=60)


# --- the failure itself --------------------------------------------------

def test_a_transfer_voids_the_starting_record_it_was_built_on():
    """The whole point. Two starts at the old club prove nothing here."""
    settled = assess(starts=2, minutes_played=180, team_games=2,
                     prior_minutes=2400, prior_appearances=31)
    moved = assess(articles=[moved_this_week()], starts=2, minutes_played=180,
                   team_games=2, prior_minutes=2400, prior_appearances=31)
    assert settled.outlook == ST.VERY_LIKELY
    assert moved.outlook != ST.VERY_LIKELY
    assert moved.new_club
    assert any("built somewhere else" in r for r in moved.reasons)


def test_current_predicted_lineups_overrule_an_older_appearance_record():
    status = assess(articles=[
        moved_this_week(),
        article("Manchester City predicted XI vs Coventry", CITY_XI_BENCHING_HIM),
        article("Man City predicted lineup to face Coventry",
                CITY_XI_BENCHING_HIM, source="Football365",
                domain="football365.com", hours_ago=10),
    ], starts=2, minutes_played=180, team_games=2)
    assert status.outlook == ST.LIKELY_BENCH
    assert status.vetoes
    assert status.lineups.benched == 2


def test_a_lineup_that_starts_him_is_read_as_starting():
    status = assess(articles=[
        article("Manchester City predicted XI vs Coventry", CITY_XI_STARTING_HIM),
        article("Man City predicted lineup", CITY_XI_STARTING_HIM,
                source="Football365", domain="football365.com", hours_ago=9),
    ], starts=2, minutes_played=180, team_games=2)
    assert status.lineups.starts == 2
    assert status.outlook in (ST.LIKELY, ST.VERY_LIKELY)
    assert status.confidence == ST.HIGH


def test_disagreeing_lineups_produce_a_coin_flip_not_a_verdict():
    status = assess(articles=[
        article("Manchester City predicted XI", CITY_XI_STARTING_HIM),
        article("Man City predicted lineup", CITY_XI_BENCHING_HIM,
                source="Football365", domain="football365.com", hours_ago=8),
    ], starts=2, minutes_played=180, team_games=2)
    assert status.outlook == ST.FIFTY_FIFTY
    assert "disagree" in " ".join(status.reasons)


# --- what the manager said -----------------------------------------------

def test_a_manager_saying_he_will_start_can_lift_a_new_signing():
    status = assess(articles=[
        moved_this_week(),
        article("Guardiola press conference: Newman will start",
                "Pep Guardiola confirmed Alex Newman will start against "
                "Coventry.", source="Man City", domain="mancity.com",
                hours_ago=4),
    ], starts=2, minutes_played=180, team_games=2)
    assert status.outlook == ST.LIKELY
    assert status.confidence == ST.HIGH
    assert status.manager_reading == se.WILL_START


def test_a_vague_manager_comment_lowers_certainty_rather_than_settling_it():
    status = assess(articles=[
        article("Guardiola on Newman: we will decide tomorrow",
                "Asked about Alex Newman, Guardiola said: we will decide "
                "tomorrow after training.", source="Man City",
                domain="mancity.com", hours_ago=3),
    ], starts=4, minutes_played=360, team_games=4,
        prior_minutes=2400, prior_appearances=31)
    assert status.outlook == ST.FIFTY_FIFTY
    assert status.manager_reading == se.UNDECIDED
    assert "not committed" in " ".join(status.reasons)


def test_a_manager_saying_he_is_not_ready_benches_him():
    status = assess(articles=[
        moved_this_week(),
        article("Guardiola: Newman is not ready to start",
                "Guardiola said Alex Newman is not ready to start yet.",
                source="Man City", domain="mancity.com", hours_ago=5),
    ], starts=2, minutes_played=180, team_games=2)
    assert status.outlook in (ST.LIKELY_BENCH, ST.VERY_UNLIKELY)


# --- absence of evidence is not evidence of security ---------------------

def test_silence_lowers_confidence_rather_than_confirming_security():
    thin = assess(starts=2, minutes_played=180, team_games=2)
    assert thin.confidence == ST.LOW
    assert any("nothing published" in r for r in thin.reasons)


def test_a_new_signing_with_no_current_coverage_is_never_high_confidence():
    status = assess(articles=[moved_this_week()], starts=2,
                    minutes_played=180, team_games=2,
                    prior_minutes=3000, prior_appearances=35)
    assert status.confidence != ST.HIGH
    assert status.outlook != ST.VERY_LIKELY


# --- but an established starter is not made uncertain by silence ---------

def test_an_established_starter_survives_a_week_with_no_journalism():
    """Part K. Most players go unwritten-about most weeks."""
    status = assess(starts=2, minutes_played=180, team_games=2,
                    prior_minutes=2953, prior_appearances=34)
    assert status.outlook == ST.VERY_LIKELY
    assert status.confidence == ST.MEDIUM
    assert not status.stale


def test_a_long_in_season_record_alone_also_carries_him():
    status = assess(starts=6, minutes_played=540, team_games=6)
    assert status.outlook == ST.VERY_LIKELY
    assert status.confidence == ST.MEDIUM


# --- official flags outrank everything -----------------------------------

def test_an_injury_flag_is_decisive_and_confident():
    status = assess(availability="i", starts=6, minutes_played=540,
                    team_games=6)
    assert status.outlook == ST.OUT
    assert status.confidence == ST.HIGH
    assert status.expected_share == 0.0


def test_a_low_chance_of_playing_is_respected():
    status = assess(chance_of_playing=25, starts=6, minutes_played=540,
                    team_games=6)
    assert status.outlook == ST.VERY_UNLIKELY


def test_a_reported_injury_moves_an_established_starter_to_a_coin_flip():
    status = assess(articles=[
        article("Newman injury update: a doubt for Saturday",
                "Alex Newman picked up a knock in training and is a doubt.",
                source="Sky Sports", domain="skysports.com", hours_ago=5),
    ], starts=6, minutes_played=540, team_games=6)
    assert status.outlook == ST.FIFTY_FIFTY
    assert status.injury


# --- recency and authority ----------------------------------------------

def test_an_old_nailed_article_cannot_outweigh_a_lineup_published_today():
    status = assess(articles=[
        article("Newman is nailed on for Everton", "Alex Newman has started "
                "every game and is nailed.", source="FPL Pulse",
                domain="fplpulse.com", hours_ago=600),
        moved_this_week(),
        article("Manchester City predicted XI", CITY_XI_BENCHING_HIM),
        article("Man City predicted lineup", CITY_XI_BENCHING_HIM,
                source="Football365", domain="football365.com", hours_ago=9),
    ], starts=2, minutes_played=180, team_games=2)
    assert status.outlook == ST.LIKELY_BENCH


def test_evidence_is_graded_on_four_independent_axes():
    graded = se.grade(
        article("Manchester City predicted XI vs Coventry", CITY_XI_BENCHING_HIM),
        ev.name_variants("Newman", "Alex Newman"),
        ev.own_tokens("Newman", "Alex Newman"), ev.mentions_this_player, NOW)
    assert graded.kind == se.PREDICTED_XI
    assert graded.tier == se.SPECIALIST
    assert graded.recency == 1.0
    assert graded.relevance == 1.0
    assert graded.weight > 0.2


def test_an_undated_item_is_not_treated_as_current():
    undated = Article(title="Manchester City predicted XI", url="u",
                      source="X", domain="sportsmole.co.uk",
                      body=CITY_XI_BENCHING_HIM)
    graded = se.grade(undated, ["Newman"], ev.own_tokens("Newman"),
                      ev.mentions_this_player, NOW)
    assert graded.recency == se.UNDATED_WEIGHT
    assert graded.weight < 0.2


def test_a_general_article_scores_far_below_a_lineup_for_this_question():
    variants = ev.name_variants("Newman", "Alex Newman")
    own = ev.own_tokens("Newman", "Alex Newman")
    lineup = se.grade(
        article("Manchester City predicted XI vs Coventry", CITY_XI_BENCHING_HIM),
        variants, own, ev.mentions_this_player, NOW)
    general = se.grade(
        article("Best Manchester City FPL assets", "Alex Newman is one option.",
                source="FPL Pulse", domain="fplpulse.com", hours_ago=500),
        variants, own, ev.mentions_this_player, NOW)
    assert lineup.weight > general.weight * 10


# --- expected minutes ----------------------------------------------------

def test_every_outlook_carries_a_minutes_range_and_a_share():
    for outlook in ST.LADDER:
        low, high = ST.MINUTES_RANGE[outlook]
        assert 0 <= low <= high <= 90
        assert 0.0 <= ST.EXPECTED_SHARE[outlook] <= 1.0
    assert ST.EXPECTED_SHARE[ST.VERY_LIKELY] > ST.EXPECTED_SHARE[ST.LIKELY_BENCH]


# --- validation ----------------------------------------------------------

def test_validation_catches_a_new_signing_still_shown_as_nailed():
    status = assess(articles=[moved_this_week()], starts=2,
                    minutes_played=180, team_games=2)
    status.outlook = ST.VERY_LIKELY          # as the old code would have it
    problems = ST.validate(status)
    assert any("changed clubs" in p for p in problems)


def test_validation_catches_old_club_evidence_under_a_new_club_badge():
    status = assess(articles=[moved_this_week()], starts=2,
                    minutes_played=180, team_games=2)
    status.outlook = ST.LIKELY
    problems = ST.validate(status, evidence_clubs={"EVE"})
    assert any("EVE" in p for p in problems)


def test_validation_catches_a_flagged_player_shown_as_starting():
    status = assess(availability="i")
    status.outlook = ST.VERY_LIKELY
    assert any("unavailable but shown as starting" in p
               for p in ST.validate(status))


def test_a_clean_status_validates():
    status = assess(starts=6, minutes_played=540, team_games=6)
    assert ST.validate(status) == []


# --- deadline awareness and the coverage metric --------------------------

def test_research_mode_follows_the_deadline():
    assert ST.research_mode(200) == ST.FULL
    assert ST.research_mode(48) == ST.DEADLINE
    assert ST.research_mode(6) == ST.DEADLINE_DAY
    assert ST.research_mode(None) == ST.FULL


def test_coverage_counts_players_checked_not_articles_collected():
    checked = [assess(articles=[
        article("Manchester City predicted XI", CITY_XI_STARTING_HIM)],
        starts=4, minutes_played=360, team_games=4) for _ in range(4)]
    report = ST.coverage(checked)
    assert report["predicted_xi_checked"] == "4/4"
    assert report["deadline_coverage"] == "GOOD"
    assert "articles" not in " ".join(report)

    thin = ST.coverage([assess(starts=4, minutes_played=360, team_games=4)])
    assert thin["deadline_coverage"] == "THIN"


def test_targeted_terms_are_built_from_the_decision_not_the_player():
    terms = se.targeted_terms("Newman", "Alex Newman", "MCI", "Man City",
                              "Coventry")
    joined = " | ".join(terms).lower()
    assert "predicted xi coventry" in joined
    assert "team news" in joined
    assert "injury" in joined

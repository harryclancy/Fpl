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


# --- defects the first live run of the freshness layer produced ----------
#
# Each of these shipped a wrong label to the page. They are the reason the
# gate on every finding is "a sentence that names him AND makes the claim"
# rather than "an article of the right kind".

SPORTS_MOLE_BODY = (
    "Brentford lineup vs. Sunderland: Predicted XI for Premier League clash. "
    "Keith Andrews has a decision to make at left-back. " + ("Filler. " * 60) +
    "Brentford possible starting lineup: Kelleher; Kayode, Ajer, Collins, "
    "Lewis-Potter; Janelt, Sangare; Ouattara, Damsgaard, Schade; Thiago "
    "Written by Ben Knapton People mentioned in this article")


def read_lineup(name, full, body=SPORTS_MOLE_BODY):
    return se.lineup_verdict(body, ev.name_variants(name, full),
                             ev.own_tokens(name, full), ev.mentions_this_player)


def test_a_lineup_with_no_substitutes_section_is_still_readable():
    """Most predicted XIs announce the eleven and never list a bench. The
    parser only looked for where the eleven ENDED, so it read none of them."""
    assert read_lineup("Thiago", "Igor Thiago") == se.STARTS
    assert read_lineup("Schade", "Kevin Schade") == se.STARTS
    assert read_lineup("Haaland", "Erling Haaland") == se.OMITTED


def test_the_lineup_is_cut_at_the_page_furniture():
    eleven, bench = se.extract_lineup(SPORTS_MOLE_BODY)
    assert "Kelleher" in eleven and "Thiago" in eleven
    assert "Written by" not in eleven
    assert bench == ""


def test_a_lineup_is_read_from_the_body_not_from_a_preview():
    """The team sheet sits two thousand characters into the page; grading
    only ever needed the opening, and the parser was handed the opening."""
    graded = se.grade(
        Article(title="Brentford lineup vs. Sunderland: Predicted XI",
                url="u", source="Sports Mole", domain="sportsmole.co.uk",
                body=SPORTS_MOLE_BODY,
                published=(NOW - timedelta(hours=4)).isoformat()),
        ev.name_variants("Thiago", "Igor Thiago"),
        ev.own_tokens("Thiago", "Igor Thiago"), ev.mentions_this_player, NOW)
    assert "Kelleher" in graded.body
    assert len(graded.excerpt) <= 300


def test_the_opponents_lineup_cannot_bench_your_whole_team():
    """"Coventry lineup vs. Man City" contains no City player. Reading it
    as City's would drop the entire side."""
    assert se.lineup_subject("Coventry lineup vs. Man City") == "Coventry lineup"
    assert se.lineup_subject("Arsenal vs Chelsea Prediction") == "Arsenal"

    city_player = assess(articles=[
        article("Coventry lineup vs. Man City: Predicted XI",
                "Coventry possible starting lineup: Collins; Thomas, Binks, "
                "Kitching, Bidwell; Eccles, Sheaf; Wright, Torp, Sakamoto; "
                "Simms Written by", hours_ago=5),
    ], starts=4, minutes_played=360, team_games=4)
    assert city_player.lineups.omitted == 0
    assert city_player.outlook != ST.LIKELY_BENCH


def test_a_bookings_watchlist_is_not_a_suspension():
    """"FPL suspensions watch: Newman, Gross among players booked so far"
    ruled a fit defender OUT."""
    status = assess(articles=[
        article("FPL suspensions watch: Newman, Gross among players booked so far",
                "Alex Newman is one booking away from a ban. Several players "
                "are on four yellow cards.", source="FF Scout",
                domain="fantasyfootballscout.co.uk", hours_ago=20),
    ], starts=4, minutes_played=360, team_games=4)
    assert status.outlook != ST.OUT
    assert not status.suspension


def test_a_club_injury_roundup_is_not_a_report_that_he_is_injured():
    status = assess(articles=[
        article("Man City injury, suspension news and return dates for Coventry",
                "Manchester City have a number of players unavailable. Rodri "
                "is out injured and Stones is a doubt.", hours_ago=8),
    ], starts=4, minutes_played=360, team_games=4)
    assert not status.injury
    assert status.outlook == ST.VERY_LIKELY


def test_a_named_injury_report_is_recorded():
    status = assess(articles=[
        article("Man City injury news",
                "Alex Newman picked up a knock in training and is a doubt for "
                "Saturday.", hours_ago=8),
    ], starts=4, minutes_played=360, team_games=4)
    assert status.injury
    assert status.outlook == ST.FIFTY_FIFTY


def test_a_manager_quote_must_be_about_him():
    """"the team news is out" and "Arsenal are out of the title race" were
    read as reports that a fit goalkeeper was unavailable."""
    status = assess(articles=[
        article("Arsenal team news", "The team news is out. Arteta said "
                "Arsenal are out of the title race already, which is absurd.",
                hours_ago=6),
    ], starts=4, minutes_played=360, team_games=4)
    assert status.outlook == ST.VERY_LIKELY
    assert not status.manager_reading


def test_another_players_transfer_is_not_his_transfer():
    """A raw count of the string "Gabriel" in an article about Gabriel
    Jesus leaving made an Arsenal centre-half a new signing."""
    status = assess(
        name="Gabriel", full="Gabriel dos Santos Magalhaes", club="ARS",
        articles=[article(
            "Barcelona complete signing of Gabriel Jesus from Arsenal",
            "Barcelona have completed the signing of Gabriel Jesus. Gabriel "
            "Jesus joins on a permanent deal. Gabriel Jesus said he was "
            "excited to join.", hours_ago=30)],
        starts=4, minutes_played=360, team_games=4)
    assert not status.new_club
    assert status.outlook == ST.VERY_LIKELY

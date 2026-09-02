"""Stage B: homepage prose composed from the research corpus.

These guard the line the whole project keeps running into — the difference
between having evidence and appearing to. Every failure below was found by
reading real generated output, not by imagining what might go wrong.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.analysis import writeup
from fpl_assistant.research.collect import Article
from fpl_assistant.research.evidence import Evidence


def _item(text, title="Manchester City team news", source="Fantasy Football Scout",
          url="https://x.com/news/a", when=None):
    article = Article(
        title=title, url=url, source=source, domain="x.com", body=text,
        published=(when or datetime.now(timezone.utc)).isoformat(), via="rss")
    return Evidence(article, "haaland", "team news")


# --- what counts as a quotable sentence ----------------------------------

def test_site_navigation_is_never_quoted_as_evidence():
    """A nav bar has no full stops, so it arrives as one long "sentence".
    This produced "Free Team Rating FPL Fixture Ticker ... Win prizes"
    quoted as reporting about Haaland."""
    nav = ("Free Team Rating FPL Fixture Ticker Gameweek 2 Live FPL Toolkit Expert "
           "Team Reveals Why Join Us Download the FFScout app Join Our Leagues Win prizes")
    assert not writeup._is_prose(nav)


def test_a_squad_list_is_not_a_sentence():
    listing = ("Kelleher Konsa Ngoyo Gvardiol De Cuyper Schade Szoboszlai Cherki "
               "Bruno Fernandes Gibbs-White Haaland Wissa Leno Egan Cash Akpom")
    assert not writeup._is_prose(listing)


def test_a_headline_question_is_not_a_finding():
    """"Should we Triple Captain Haaland?" is a prompt. Quoting it back as
    evidence dresses a title up as reporting."""
    assert not writeup._is_prose("Should we Triple Captain Haaland in FPL Gameweek 3?")


def test_real_reporting_passes():
    assert writeup._is_prose(
        "Pep Guardiola confirmed that Erling Haaland trained fully on Friday and is "
        "expected to start against Coventry City at the Etihad.")


def test_the_feed_tail_is_stripped():
    """Nearly every RSS excerpt ends with "The post X appeared first on Y"."""
    text = ("Haaland scored twice against Palace despite barely touching the ball in "
            "the first half of the contest. The post FPL notes appeared first on Scout.")
    got = writeup._sentences(text)
    assert got and all("appeared first on" not in s for s in got)


def test_an_excerpt_that_only_repeats_the_headline_is_not_quoted():
    title = "Haaland ruled out of the Coventry game with a knee injury sustained in training"
    assert writeup._sentences(title, exclude_title=title) == []


def test_byline_and_comment_chrome_is_stripped_from_the_front():
    """Real output began "September 1 254 comments 1 September 2026 254 comments As
    Manchester City prepare…" — the prose after the chrome was fine."""
    raw = ("1 September 2026 | 254 comments As Manchester City prepare to host Coventry "
           "City in Gameweek 3, managers are weighing the Triple Captain chip.")
    cleaned = writeup._clean(raw)
    assert cleaned.startswith("As Manchester City prepare")


def test_mojibake_is_repaired_rather_than_quoted_back():
    assert "don’t" in writeup._clean(
        "This week he covers what to do about Haaland if you donâ€™t own him and more.")


# --- composition ---------------------------------------------------------

def test_a_quote_is_never_used_in_two_sections():
    """One fact under four headings reads as four pieces of evidence.

    Note the deliberate exception this does NOT test: with two or fewer
    quotes the dedup is suspended, because strict deduplication on a player
    with one retrieved sentence leaves most sections empty and reads as no
    evidence when there is some. Four quotes is comfortably past that.
    """
    items = [
        _item("Erling Haaland scored twice against Crystal Palace and looked sharp "
              "throughout the second half of the contest at Selhurst Park."),
        _item("Haaland has an injury concern after taking a knock late on and is rated "
              "a doubt for the trip to face Coventry City this weekend.",
              url="https://x.com/news/b"),
        _item("The manager confirmed in his press conference that Haaland would be "
              "assessed again on Friday before any decision was taken on selection.",
              url="https://x.com/news/c"),
        _item("Haaland has scored in each of his last four appearances at the Etihad "
              "Stadium and the fixture run ahead looks kind for Manchester City.",
              url="https://x.com/news/d"),
    ]
    made = writeup.build("Haaland", "MCI", items, price=15.5)
    seen = []
    for section in (made.status, made.case_for, made.case_against,
                    made.expected_minutes, made.developments, made.outlook):
        for quote in made.quotes:
            if quote.text in section:
                seen.append(quote.text)
    assert len(seen) == len(set(seen)), "a quote appeared in more than one section"


def test_absence_of_bad_news_is_not_reported_as_a_clearance():
    """The Enzo rule, applied to prose: nobody saying he is injured is not
    the same as someone saying he is fit."""
    items = [_item("Haaland scored twice against Palace and was excellent throughout "
                   "the whole of the second half at Selhurst Park on Friday night.")]
    made = writeup.build("Haaland", "MCI", items, price=15.5)
    assert "absence of a negative report" in made.case_against
    assert "weaker than a positive clearance" in made.case_against


def test_a_player_nobody_wrote_about_gets_an_honest_gap_not_a_verdict():
    made = writeup.build("Mitchell", "CRY", [], price=4.5)
    assert "gap in the reporting" in made.status
    assert made.confidence == "none"
    assert not made.has_prose


def test_prose_requires_a_real_quote_not_a_fallback_sentence():
    """has_prose reported 15/15 when six players had no quote at all — the
    fallback text is this module talking, not reporting."""
    empty = writeup.build("Mitchell", "CRY", [], price=4.5)
    assert not empty.has_prose
    real = writeup.build("Haaland", "MCI", [
        _item("Haaland trained fully on Friday and will start against Coventry City "
              "at the Etihad Stadium this weekend, the manager confirmed.")], price=15.5)
    assert real.has_prose


def test_conflicting_minutes_evidence_is_reported_as_conflict():
    items = [
        _item("Haaland trained fully on Friday and is expected to start the match "
              "against Coventry City at the Etihad this weekend."),
        _item("Haaland is a major doubt after picking up an injury and could be "
              "ruled out of the weekend fixture entirely, according to reports.",
              url="https://x.com/news/b"),
    ]
    made = writeup.build("Haaland", "MCI", items, price=15.5)
    assert "disagree" in made.expected_minutes


def test_every_write_up_records_the_evidence_behind_it():
    items = [_item("Haaland trained fully on Friday and will start against Coventry "
                   "City at the Etihad Stadium this weekend, the manager confirmed.")]
    made = writeup.build("Haaland", "MCI", items, price=15.5)
    assert made.evidence_used == ["https://x.com/news/a"]
    assert made.sources_used == ["Fantasy Football Scout"]


# --- transfers -----------------------------------------------------------

def test_a_transfer_with_no_evidence_says_so_rather_than_inventing_a_case():
    out = writeup.build("Kayode", "BRE", [], price=4.6)
    into = writeup.build("Cherki", "MCI", [], price=7.6)
    case = writeup.transfer(out, into)
    assert case.confidence == "low"
    assert "would be guessing" in case.why_in


def test_a_transfer_is_argued_from_both_players_evidence():
    out = writeup.build("Kayode", "BRE", [
        _item("Kayode is a doubt for the weekend after an injury in training and may "
              "be rested by his manager for the coming fixture at home.")], price=4.6)
    into = writeup.build("Cherki", "MCI", [
        _item("Cherki scored twice and created a chance every sixteen minutes, and is "
              "expected to start again against Coventry City this weekend.")], price=7.6)
    case = writeup.transfer(out, into, out_run=["ARS (A)"], in_run=["COV (H)"])
    assert "doubt" in case.why_out.lower() or "injury" in case.why_out.lower()
    assert "Cherki" in case.why_in or "scored" in case.why_in
    assert case.confidence == "high"
    assert "COV (H)" in case.next_few_gameweeks


def test_the_alternative_is_argued_against_not_ignored():
    into = writeup.build("Cherki", "MCI", [
        _item("Cherki scored twice at Selhurst Park and is expected to keep his place "
              "in the side for the visit of Coventry City this weekend.")], price=7.6)
    alternative = writeup.build("Foden", "MCI", [
        _item("Foden missed two big chances and has been struggling for form, and could "
              "be rotated out of the side for the weekend fixture at the Etihad.")],
        price=7.0)
    case = writeup.transfer(writeup.build("X", "BRE", [], price=4.5), into, alternative)
    assert case.alternative == "Foden"
    assert "Foden" in case.why_not_alternative


def test_an_abbreviation_does_not_split_a_sentence_in_half():
    """"St James' Park" split into a fragment beginning "James' Park with a
    point in Sunday's draw", which was then quoted as a source's words."""
    text = ("Newcastle were held at St James' Park with a point in Sunday's 2-2 draw, "
            "thanks to Dominik Szoboszlai's late leveller from the penalty spot.")
    got = writeup._sentences(text)
    assert len(got) == 1, got
    assert got[0].startswith("Newcastle were held")


def test_a_fragment_starting_mid_clause_is_rejected():
    assert not writeup._is_prose(
        "james' Park with a point in Sunday's draw, thanks to a late leveller.")

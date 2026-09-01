"""The adaptive large-corpus research engine: the five stages.

What these guard is not "does the code run" but "does it stay honest as it
gets bigger". A pipeline that discovers a thousand items has a thousand new
chances to inflate a number, and every one of the failures already found in
this project was a count that looked good and meant nothing.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.research import collect, dedupe, extract, pipeline, ranking

SQUAD = [
    {"name": "Haaland", "team": "MCI", "position": "FWD", "price": 15.5, "status": "a"},
    {"name": "Szoboszlai", "team": "LIV", "position": "MID", "price": 7.0, "status": "a"},
    {"name": "Mitchell", "team": "CRY", "position": "DEF", "price": 4.5, "status": "a",
     "on_bench": True},
]


def _article(**kw):
    base = dict(title="Manchester City team news ahead of Coventry",
                url="https://example.com/news/city-team-news",
                source="Example", domain="example.com", via="rss",
                published=datetime.now(timezone.utc).isoformat())
    base.update(kw)
    return collect.Article(**base)


# --- stage 5: reading a page --------------------------------------------

def test_extracts_prose_and_ignores_scripts_and_navigation():
    html = """<html><head><style>.a{color:red}</style></head><body>
      <nav>Home Fixtures Tickets</nav>
      <script>var x = 1;</script>
      <p>Pep Guardiola confirmed that Erling Haaland trained fully on Friday and
      will start against Coventry City. The manager said: "He is ready, he has had
      a good week and there is no issue with the knock he took last weekend."</p>
      <p>City are expected to name an unchanged side, with Rayan Cherki retaining
      his place after scoring twice at Selhurst Park last time out. The only doubt
      concerns the left-back position where rotation remains possible.</p>
      <footer>All rights reserved</footer></body></html>"""
    result = extract.from_html(html)
    assert result.ok
    assert "Guardiola confirmed" in result.text
    assert "var x" not in result.text and "color:red" not in result.text
    assert "Home Fixtures Tickets" not in result.text or result.text.count("Tickets") <= 1


def test_a_cookie_wall_is_not_an_article_body():
    """A paywall, a consent notice and a 404 all return text. Storing that
    as an article body fills the corpus with pages mentioning no player."""
    wall = ("<html><body><nav>Home Fixtures</nav>"
            + "<p>Accept all cookies to continue. Manage cookies. Sign in. "
              "Subscribe. Privacy policy. Terms of use.</p>" * 12
            + "</body></html>")
    result = extract.from_html(wall)
    assert not result.ok
    assert "characters of prose" in result.reason, result.reason


def test_topics_are_detected_so_evidence_breadth_can_be_measured():
    text = ("Arne Slot said in his press conference that Szoboszlai is fit. "
            "The injury to Bradley means rotation. His expected goals involvement "
            "has been strong and he takes the penalties.")
    topics = extract.topics_in(text)
    assert "press conference" in topics
    assert "injury" in topics
    assert "set pieces" in topics
    assert "statistics" in topics


# --- stage 3: deduplication ---------------------------------------------

def test_syndicated_rewrites_of_one_story_collapse_to_one():
    """Thirty rewrites of one press conference are one claim reported
    thirty times. Counting them separately turns repetition into fake
    corroboration."""
    articles = [
        _article(title="Man City eye Enzo Fernandez move before deadline",
                 url="https://a.com/1", domain="a.com"),
        _article(title="Manchester City eyeing move for Enzo Fernandez before deadline",
                 url="https://b.com/2", domain="b.com"),
        _article(title="Enzo Fernandez: Man City eye move before the deadline",
                 url="https://c.com/3", domain="c.com"),
    ]
    kept, removed = dedupe.apply(articles)
    assert len(kept) == 1
    assert removed == 2
    assert kept[0].duplicate_count == 3
    assert len(kept[0].duplicate_urls) == 2


def test_two_different_stories_about_the_same_player_stay_separate():
    articles = [
        _article(title="Haaland scores twice against Bournemouth", url="https://a.com/1"),
        _article(title="Haaland ruled out of Coventry game with knee injury",
                 url="https://b.com/2"),
    ]
    kept, removed = dedupe.apply(articles)
    assert len(kept) == 2 and removed == 0


def test_the_outlet_suffix_does_not_stop_a_match():
    assert dedupe.similarity(
        "Enzo Fernandez agrees terms with Manchester City | Football365",
        "Enzo Fernandez agrees terms with Manchester City - Sky Sports") > 0.9


def test_the_primary_kept_is_the_better_source_not_a_rewrite():
    tier_of = lambda a: 1 if a.domain == "official.com" else 4
    articles = [
        _article(title="Haaland fit to face Coventry says Guardiola",
                 url="https://blog.com/1", domain="blog.com"),
        _article(title="Guardiola says Haaland is fit to face Coventry",
                 url="https://official.com/1", domain="official.com"),
    ]
    kept, _ = dedupe.apply(articles, tier_of)
    assert len(kept) == 1
    assert kept[0].domain == "official.com"


# --- stage 4: ranking ----------------------------------------------------

def test_a_player_in_the_headline_outranks_a_passing_mention():
    named = _article(title="Haaland fit to start against Coventry")
    passing = _article(title="Premier League weekend preview",
                       excerpt="Elsewhere, Haaland is expected to feature.")
    assert (ranking.score(named, SQUAD, 3).total
            > ranking.score(passing, SQUAD, 3).total)


def test_fresh_beats_stale_all_else_equal():
    old = _article(published=(datetime.now(timezone.utc) - timedelta(days=18)).isoformat())
    new = _article()
    assert ranking.score(new, SQUAD, 3).total > ranking.score(old, SQUAD, 3).total


def test_an_official_club_source_outranks_a_blog_saying_the_same_thing():
    official = _article(domain="mancity.com", source="Manchester City")
    blog = _article(domain="somefplblog.com", source="Blog")
    assert (ranking.score(official, SQUAD, 3, tier=2).total
            > ranking.score(blog, SQUAD, 3, tier=4).total)


def test_an_article_about_a_previous_gameweek_is_marked_down():
    """"Do not let stale GW2 analysis dominate GW3." Explicitly naming an
    older gameweek is worse than naming none."""
    old_gw = _article(title="FPL Gameweek 2 review and takeaways")
    neutral = _article(title="Manchester City injury update before the weekend")
    assert (ranking.score(neutral, SQUAD, 3).total
            > ranking.score(old_gw, SQUAD, 3).total)


def test_ticket_news_is_scored_to_the_floor():
    admin = _article(title="Manchester City ticket information for Coventry")
    real = _article(title="Manchester City team news for Coventry")
    assert ranking.score(admin, SQUAD, 3).total < ranking.score(real, SQUAD, 3).total / 2


# --- adaptive effort -----------------------------------------------------

def test_a_flagged_player_is_prioritised():
    assert pipeline.priority_for({"status": "d", "team": "MCI", "name": "X"}) == "high"
    assert pipeline.priority_for(
        {"status": "a", "chance_of_playing_next_round": 50, "name": "X"}) == "high"


def test_cheap_bench_fodder_is_deprioritised():
    assert pipeline.priority_for(
        {"status": "a", "on_bench": True, "price": 4.0, "name": "X"}) == "low"


def test_a_well_evidenced_player_stops_earning_effort():
    record = pipeline.PlayerRecord(name="Haaland", club="MCI", evidence_count=9)
    assert pipeline.priority_for({"status": "a", "name": "Haaland"}, record) == "low"


def test_a_player_short_of_evidence_is_escalated_regardless_of_status():
    record = pipeline.PlayerRecord(name="Kayode", club="BRE", evidence_count=1)
    assert pipeline.priority_for({"status": "a", "name": "Kayode"}, record) == "high"


# --- the report ----------------------------------------------------------

def test_the_report_counts_researched_players_from_records_not_from_hope():
    report = pipeline.RunReport()
    report.players = {
        "A": pipeline.PlayerRecord(name="A", club="MCI", evidence_count=5),
        "B": pipeline.PlayerRecord(name="B", club="LIV", evidence_count=1),
    }
    assert report.players_researched == 1


def test_evidence_strength_bands_match_the_brief():
    def strength(count):
        return pipeline.PlayerRecord(name="x", club="MCI", evidence_count=count).strength
    assert strength(2) == "short"
    assert strength(3) == "minimum"
    assert strength(5) == "good"
    assert strength(8) == "strong"


def test_a_player_record_reports_every_completeness_field():
    """The eleven fields the brief asks to be stored per player."""
    record = pipeline.PlayerRecord(name="Haaland", club="MCI").as_dict()
    for field in ("evidence_count", "source_count", "latest_evidence",
                  "official_source_found", "fpl_source_found", "team_news_found",
                  "starting_status_assessed", "injury_status_assessed",
                  "transfer_status_assessed", "role_assessed", "fixtures_assessed"):
        assert field in record, f"{field} missing from the player research record"


# --- discovery must not let big sources starve small ones ----------------

class _FakeSession:
    pass


def test_every_source_is_attempted_before_the_ceiling_bites(monkeypatch):
    """The regression this fixes: walking the source list and stopping at
    1000 candidates meant forty large sitemaps consumed the whole budget
    and the other thirty-eight sources — including every official club RSS
    feed — were never asked. Squad coverage fell from 15/15 to 7/15."""
    big = [_article(url=f"https://big.com/news/{i}", domain="big.com") for i in range(500)]
    small = [_article(url="https://club.com/news/team-news", domain="club.com")]

    def fake_collect(source, session, **kwargs):
        return (list(big) if source["domain"] == "big.com" else list(small)), ""

    monkeypatch.setattr(pipeline.collect, "collect_from", fake_collect)

    sources = [{"domain": "big.com", "tier": 3}] * 40 + [{"domain": "club.com", "tier": 2}]
    candidates, failures, readable = pipeline.discover(
        sources, _FakeSession(), max_candidates=100)

    assert readable == 41, "every source must be attempted"
    domains = {a.domain for a in candidates}
    assert "club.com" in domains, "the small source must survive the ceiling"


def test_the_ceiling_is_respected():
    """Discovery is capped, and the cap is reported rather than silent."""
    big = [_article(url=f"https://big.com/news/{i}", domain="big.com") for i in range(500)]

    def fake_collect(source, session, **kwargs):
        return list(big), ""

    import types
    module = types.SimpleNamespace(collect_from=fake_collect)
    original = pipeline.collect.collect_from
    pipeline.collect.collect_from = fake_collect
    try:
        candidates, failures, _ = pipeline.discover(
            [{"domain": "big.com", "tier": 3}] * 3, _FakeSession(), max_candidates=50)
    finally:
        pipeline.collect.collect_from = original

    assert len(candidates) == 50
    assert any("ceiling" in f for f in failures)


def test_the_coverage_gate_fails_when_half_the_squad_is_unevidenced():
    """A gate that cannot fail is not a gate. The earlier version passed
    when any single player was researched, so 7/15 reported as success."""
    from fpl_assistant.research import evidence, gates

    def player(name, researched):
        found = evidence.PlayerEvidence(player=name, club="MCI", corpus_size=900)
        if researched:
            found.items = [
                evidence.Evidence(_article(title=f"{name} starts against Coventry",
                                           url=f"https://x.com/news/{name}-{i}"), name.lower())
                for i in range(3)
            ]
        return found

    half = {f"P{i}": player(f"P{i}", i < 7) for i in range(15)}
    assert not gates.check_squad_coverage(half, 15)

    nearly = {f"P{i}": player(f"P{i}", i < 13) for i in range(15)}
    assert gates.check_squad_coverage(nearly, 15), "one or two genuinely uncovered is fine"


def test_coverage_is_assessed_against_the_whole_corpus_not_one_run(monkeypatch):
    """The cache exists so evidence ACCUMULATES. Assessing coverage against
    only what a run just fetched means every incremental pass reports the
    squad as unresearched — it only downloaded what was new since
    yesterday. A full pass reported 9/15 this way while the corpus held
    ample evidence for all fifteen."""
    known = [
        _article(title=f"Haaland starts against Coventry, part {i}",
                 url=f"https://old.com/news/haaland-{i}")
        for i in range(4)
    ]
    fresh = [_article(title="Squad news roundup", url="https://new.com/news/roundup")]

    def fake_collect(source, session, **kwargs):
        return list(fresh), ""

    monkeypatch.setattr(pipeline.collect, "collect_from", fake_collect)
    monkeypatch.setattr(pipeline, "deep_read", lambda *a, **k: [])

    _, report = pipeline.run([{"domain": "new.com", "tier": 3}],
                             [SQUAD[0]], gameweek=3, session=_FakeSession(),
                             known=known)
    assert report.players["Haaland"].evidence_count >= 4, (
        "evidence already in the corpus must still count"
    )
    assert report.players_researched == 1

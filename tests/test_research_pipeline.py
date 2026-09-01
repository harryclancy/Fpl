"""Stage A: the research collection pipeline.

The bug these guard against, stated once: the app had no way to retrieve a
news article. The Refresh button called `st.cache_data.clear()`, every
write-up came from hand-typed JSON, and a player nobody had typed about
rendered as "unchecked" forever. Pressing Refresh could not change that.

So the tests here are mostly about honesty rather than about parsing:
a run that retrieves nothing must SAY it retrieved nothing, and a match
that is really a generated tool page must not be counted as research.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.research import collect, corpus as corpus_mod, evidence, gates

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Should we Triple Captain Haaland in FPL Gameweek 3?</title>
    <link>https://example.com/2026/09/01/triple-captain-haaland</link>
    <pubDate>Tue, 01 Sep 2026 11:45:00 +0000</pubDate>
    <description>Manchester City play Coventry City at home.</description>
  </item>
  <item>
    <title>Liverpool team news: Szoboszlai fit, three defenders out</title>
    <link>https://example.com/2026/09/01/liverpool-team-news</link>
    <pubDate>Tue, 01 Sep 2026 09:00:00 +0000</pubDate>
    <description>Arne Slot's injury update ahead of Ipswich.</description>
  </item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Semenyo starts as City name unchanged side</title>
    <link rel="alternate" href="https://example.com/news/semenyo-starts"/>
    <published>2026-09-01T10:00:00Z</published>
    <summary>The winger keeps his place.</summary>
  </entry>
</feed>"""


def _article(**kw):
    base = dict(title="A headline with several words", url="https://example.com/news/x",
                source="Example", domain="example.com", via="rss",
                published=datetime.now(timezone.utc).isoformat())
    base.update(kw)
    return collect.Article(**base)


# --- parsing -------------------------------------------------------------

def test_reads_rss_without_knowing_it_is_rss():
    entries = collect.parse_feed(RSS)
    assert len(entries) == 2
    assert entries[0]["title"].startswith("Should we Triple Captain")
    assert entries[0]["url"].endswith("triple-captain-haaland")
    assert "Coventry" in entries[0]["excerpt"]


def test_reads_atom_through_the_same_function():
    """RSS and Atom disagree about every element name. Walking by local tag
    name is what stops half the sources being silently unreadable."""
    entries = collect.parse_feed(ATOM)
    assert len(entries) == 1
    assert entries[0]["url"] == "https://example.com/news/semenyo-starts"


def test_a_page_that_is_not_a_feed_parses_to_nothing_rather_than_raising():
    assert collect.parse_feed("<html><body>not a feed</body></html>") == []
    assert collect.parse_feed("") == []


# --- the tool-page problem ----------------------------------------------

def test_a_generated_profile_page_is_not_an_article():
    """The first live run counted fplpulse.com/players/haaland/1, titled
    "1", as evidence about Haaland. Three pages of that shape made Semenyo
    read as "researched — 3 items" when nobody had written about him."""
    assert not _article(title="1", url="https://x.com/players/haaland/1",
                        via="sitemap").is_article
    assert not _article(title="Antoine semenyo", via="sitemap",
                        url="https://x.com/players/antoine-semenyo").is_article
    assert not _article(title="Anderson vs szoboszlai", via="sitemap",
                        url="https://x.com/compare/anderson-vs-szoboszlai").is_article


def test_a_real_article_from_a_sitemap_still_counts():
    assert _article(title="Liverpool team news: three defenders ruled out",
                    url="https://x.com/news/liverpool-team-news-september",
                    via="sitemap").is_article


def test_an_rss_entry_is_trusted_as_writing():
    """A feed only lists things that were published, so the bar is lower."""
    assert _article(title="Haaland brace", via="rss").is_article


# --- evidence ------------------------------------------------------------

def test_finds_a_player_by_surname_in_a_headline():
    articles = [_article(title="Should we Triple Captain Haaland in Gameweek 3?")]
    found = evidence.search("Haaland", "MCI", articles)
    assert found.researched is False, "one article is below the threshold"
    assert len(found.substantive_items) == 1
    assert found.items[0].matched_on == "haaland"


def test_accents_do_not_hide_a_player():
    """Guéhi in FPL, Guehi in half the headlines."""
    articles = [_article(title="Guehi impresses again for Manchester City")]
    assert evidence.search("Guéhi", "MCI", articles).items


def test_a_common_surname_needs_the_club_to_match():
    """"Wright" alone matches Haji Wright, Ian Wright and the word itself."""
    off_club = [_article(title="Wright ruled out for Coventry with quad injury")]
    assert not evidence.search("Wright", "ARS", off_club).items
    assert evidence.search("Wright", "COV", off_club).items


def test_tool_pages_do_not_make_a_player_look_researched():
    articles = [
        _article(title="1", url="https://x.com/players/semenyo/1", via="sitemap"),
        _article(title="2", url="https://x.com/players/semenyo/2", via="sitemap"),
        _article(title="Antoine semenyo", via="sitemap",
                 url="https://x.com/players/antoine-semenyo"),
    ]
    found = evidence.search("Semenyo", "MCI", articles)
    assert found.items, "they still matched"
    assert not found.researched, "but none of them is writing"
    assert "no article written about him" in found.status


def test_the_club_fallback_covers_a_player_nobody_named():
    """A squad player nobody wrote about still gets his club's team news,
    labelled as club-level rather than passed off as being about him."""
    articles = [
        _article(title="Crystal Palace team news: predicted line-up against Fulham",
                 url="https://x.com/news/palace-team-news-fulham"),
        _article(title="Palace injury update ahead of the weekend",
                 url="https://x.com/news/palace-injury-update"),
        _article(title="Crystal Palace press conference: Sage on his selection",
                 url="https://x.com/news/palace-press-conference"),
    ]
    found = evidence.search("Mitchell", "CRY", articles)
    assert found.items
    assert "club team news" in found.fallbacks_used
    assert all(e.kind == "club team news" for e in found.items)


# --- the gates -----------------------------------------------------------

def test_a_run_that_retrieved_nothing_is_not_a_success():
    verdict = gates.check_collection(sources_checked=60, sources_ok=0, articles=0)
    assert not verdict
    assert verdict.headline == gates.COLLECTION_FAILURE


def test_a_healthy_run_passes():
    assert gates.check_collection(63, 52, 1747)


def test_simultaneous_silence_about_the_biggest_names_is_reported_as_a_bug():
    """The check that would have caught this the day it appeared. Haaland,
    Szoboszlai and Semenyo cannot all be un-newsworthy on the same day."""
    empty = {name: evidence.PlayerEvidence(player=name, club="MCI", corpus_size=500)
             for name in ("Haaland", "Szoboszlai", "Semenyo")}
    verdict = gates.check_blackout(empty)
    assert not verdict
    assert verdict.headline == gates.PIPELINE_FAILURE


def test_one_evidenced_bellwether_is_enough_to_clear_the_blackout_check():
    found = evidence.PlayerEvidence(player="Haaland", club="MCI", corpus_size=500)
    found.items = [evidence.Evidence(_article(title="Haaland scores twice"), "haaland")]
    empty = evidence.PlayerEvidence(player="Semenyo", club="MCI", corpus_size=500)
    assert gates.check_blackout({"Haaland": found, "Semenyo": empty})


def test_a_bellwether_evidenced_only_by_tool_pages_still_trips_the_gate():
    """Otherwise the blackout check passes on exactly the junk that caused
    the problem."""
    junk = evidence.PlayerEvidence(player="Haaland", club="MCI", corpus_size=500)
    junk.items = [evidence.Evidence(
        _article(title="1", url="https://x.com/players/haaland/1", via="sitemap"), "haaland")]
    assert not gates.check_blackout({"Haaland": junk})


# --- the cache -----------------------------------------------------------

def test_merging_keeps_one_record_per_url_and_never_loses_an_excerpt():
    store = corpus_mod.Corpus(items=[_article(url="https://a", excerpt="the full story")])
    corpus_mod.merge(store, [_article(url="https://a", excerpt="",
                                      retrieved="2099-01-01T00:00:00")])
    assert len(store) == 1
    assert store.items[0].excerpt == "the full story", "a sitemap re-fetch must not erase prose"


def test_pruning_drops_stale_items_but_keeps_undated_ones():
    old = _article(url="https://old",
                   published=(datetime.now(timezone.utc) - timedelta(days=90)).isoformat())
    undated = _article(url="https://undated", published="")
    store = corpus_mod.prune(corpus_mod.Corpus(items=[old, undated]))
    urls = {a.url for a in store.items}
    assert "https://old" not in urls
    assert "https://undated" in urls, "most club sitemaps carry no date at all"


def test_a_sitemap_lastmod_is_not_treated_as_a_publication_date():
    """Reading <lastmod> as "published" made pages that were merely
    re-rendered today look like today's team news."""
    article = _article(via="sitemap", published="", modified="2026-09-01T20:00:00+00:00")
    assert article.published_at is None
    assert article.age_hours() is None


# --- the shipped pipeline state -----------------------------------------

DATA = Path(__file__).resolve().parent.parent / "data"


def test_the_source_audit_is_committed_and_finds_usable_sources():
    """A canary. If a future change breaks discovery, this goes red before
    anyone opens the app and sees empty write-ups."""
    import json
    audit = json.loads((DATA / "sources" / "discovery.json").read_text())
    counts = audit["counts"]
    assert counts["usable"] >= 40, f"only {counts['usable']} sources are machine-readable"
    assert counts["A"] >= 15, "feeds are the backbone; too few were found"


def test_every_official_club_site_can_be_read_by_the_program():
    """Twenty clubs, twenty readable sources. Nine were unusable until the
    probe learned to read robots.txt, and the gap showed up directly as
    Brentford and Palace players having no evidence."""
    import json
    audit = json.loads((DATA / "sources" / "discovery.json").read_text())
    by_domain = {s["domain"]: s for s in audit["sources"]}
    clubs = [
        "arsenal.com", "avfc.co.uk", "afcb.co.uk", "brentfordfc.com",
        "brightonandhovealbion.com", "chelseafc.com", "ccfc.co.uk", "cpfc.co.uk",
        "evertonfc.com", "fulhamfc.com", "wearehullcity.co.uk", "itfc.co.uk",
        "leedsunited.com", "liverpoolfc.com", "mancity.com", "manutd.com",
        "newcastleunited.com", "nottinghamforest.co.uk", "safc.com",
        "tottenhamhotspur.com",
    ]
    unusable = [c for c in clubs
                if by_domain.get(c, {}).get("grade") not in collect.USABLE_GRADES]
    assert not unusable, f"official club sites with no discovery method: {unusable}"


def test_the_committed_corpus_actually_contains_articles():
    """The whole point. An empty corpus means the app is guessing again."""
    store = corpus_mod.load()
    assert len(store) > 100, f"corpus holds only {len(store)} items"
    real = [a for a in store.items if a.is_article]
    assert len(real) > 50, f"only {len(real)} of {len(store)} items are actual writing"


def test_the_biggest_names_in_the_game_have_evidence_in_the_shipped_corpus():
    """The exact complaint, as a test: Haaland, Szoboszlai and Semenyo all
    returning nothing at once is the symptom that started this."""
    store = corpus_mod.load()
    found = {name: evidence.search(name, club, store.items)
             for name, club in (("Haaland", "MCI"), ("Szoboszlai", "LIV"), ("Semenyo", "MCI"))}
    for name, ev in found.items():
        assert ev.substantive_items, f"{name} has no evidence in the committed corpus"
    assert gates.check_blackout(found), "the blackout gate should pass on shipped data"

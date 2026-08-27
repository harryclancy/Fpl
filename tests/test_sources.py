"""The 100 verified-readable sources.

Every domain here was tested by running a domain-scoped search and
confirming it returned readable article text. The tests exist to keep that
promise honest, because the failure mode is invisible from the outside: a
domain the search API rejects fails the ENTIRE search it appears in, so
one unverified entry in a group of six silently loses the other five. A
research pass built on an unchecked list returns less than one built on a
third as many verified domains, and gives no clue why.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.research import sources

RAW = json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "sources" / "verified_sources.json").read_text()
)


def test_there_are_exactly_one_hundred():
    assert len(sources.load()) == 100


def test_every_single_one_is_flagged_verified():
    assert all(entry["VERIFIED_READABLE"] is True for entry in RAW["sources"])


def test_an_unverified_entry_is_refused_rather_than_loaded(tmp_path):
    """The file's promise has to survive a careless edit."""
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"sources": [
        {"name": "Good", "domain": "a.com", "tier": 1, "VERIFIED_READABLE": True},
        {"name": "Unchecked", "domain": "b.com", "tier": 1, "VERIFIED_READABLE": False},
        {"name": "Silent", "domain": "c.com", "tier": 1},
    ]}))
    assert [s.domain for s in sources.load(path)] == ["a.com"]


def test_no_domain_appears_twice():
    """Roughly a hundred genuinely different sources, not one site listed
    under several URLs to pad the count."""
    domains = [s.domain for s in sources.load()]
    assert len(domains) == len(set(domains))


# --- the exclusions, which are capability limits not preferences ---------

BANNED = ("youtube.com", "youtu.be", "x.com", "twitter.com", "reddit.com")

CRAWLER_BLOCKED = (
    "football.london", "manchestereveningnews.co.uk", "birminghammail.co.uk",
    "liverpoolecho.co.uk", "chroniclelive.co.uk", "nottinghampost.com",
    "hulldailymail.co.uk", "coventrytelegraph.net", "theargus.co.uk",
    "sunderlandecho.com", "bournemouthecho.co.uk", "yorkshireeveningpost.co.uk",
    "mylondon.news", "eadt.co.uk", "standard.co.uk", "dailymail.co.uk",
    "thesun.co.uk", "talksport.com", "bbc.com", "bbc.co.uk", "theguardian.com",
    "independent.co.uk", "metro.co.uk", "reuters.com", "transfermarkt.com",
)


def _is(domain: str, banned: str) -> bool:
    """Whether a domain IS the banned host or a subdomain of it.

    Substring matching would be wrong in a way that looks right:
    "fantasyfootballfix.com" contains "x.com", and "fplbet.com" contains
    "bet.com". Matching on the label boundary is the only correct test.
    """
    domain = domain.lower().lstrip(".")
    banned = banned.lower().lstrip(".")
    return domain == banned or domain.endswith("." + banned)


def test_no_youtube_no_x_no_reddit():
    for source in sources.load():
        for banned in BANNED:
            assert not _is(source.domain, banned), (
                f"{source.domain} cannot be read by a search"
            )


def test_no_publisher_that_blocks_the_crawler():
    """Each of these was confirmed by the search API rejecting it by name.
    One of them in a search group takes the whole group down with it."""
    for source in sources.load():
        for blocked in CRAWLER_BLOCKED:
            assert not _is(source.domain, blocked), (
                f"{source.domain} would break its search group"
            )


def test_the_ban_matches_on_domain_boundaries_not_substrings():
    """Guards the guard. A substring check would ban fantasyfootballfix.com
    for containing "x.com", which is exactly the kind of quiet wrongness
    these tests exist to catch."""
    assert _is("x.com", "x.com")
    assert _is("www.x.com", "x.com")
    assert not _is("fantasyfootballfix.com", "x.com")
    assert not _is("fplbet.com", "bet.com")


def test_the_counts_the_file_advertises_are_true():
    counts = RAW["counts"]
    assert counts["verified_readable"] == 100
    assert counts["blocked"] == 0
    assert counts["youtube"] == 0
    assert counts["x_twitter"] == 0
    assert counts["inaccessible"] == 0


# --- structure -----------------------------------------------------------

def test_every_source_says_what_it_is_used_for():
    """A source with no stated purpose is one nobody will think to search."""
    for source in sources.load():
        assert source.name.strip()
        assert source.url.startswith("http")
        assert source.used_for.strip(), f"{source.name} has no stated use"
        assert source.tier in sources.TIER_NAMES


def test_all_twenty_club_sites_are_present_in_tier_two():
    clubs = {
        "arsenal.com", "avfc.co.uk", "afcb.co.uk", "brentfordfc.com",
        "brightonandhovealbion.com", "chelseafc.com", "ccfc.co.uk", "cpfc.co.uk",
        "evertonfc.com", "fulhamfc.com", "wearehullcity.co.uk", "itfc.co.uk",
        "leedsunited.com", "liverpoolfc.com", "mancity.com", "manutd.com",
        "newcastleunited.com", "nottinghamforest.co.uk", "safc.com",
        "tottenhamhotspur.com",
    }
    tier_two = {s.domain for s in sources.plan().by_tier(2)}
    assert tier_two == clubs
    assert len(tier_two) == 20


def test_fpl_specialists_are_the_largest_tier():
    plan = sources.plan()
    assert len(plan.by_tier(1)) > len(plan.by_tier(3)) + len(plan.by_tier(4))


# --- the research order --------------------------------------------------

def test_availability_is_researched_before_anything_that_depends_on_it():
    """A captaincy case for a player who has been ruled out is worse than
    no case at all — it looks authoritative and it is void."""
    steps = [step for step, _ in sources.RESEARCH_STEPS]

    assert steps[0] == "Official club news and press conferences"
    assert steps[1] == "Injury and expected-minutes information"
    assert steps.index("Injury and expected-minutes information") < steps.index("Captaincy consensus")
    assert steps.index("Injury and expected-minutes information") < steps.index("Underlying statistics")


def test_the_plan_starts_with_the_club_sites():
    first = sources.plan().groups[0]
    assert first.tier == 2
    assert first.step == "Official club news and press conferences"


def test_searches_are_grouped_small_enough_to_stay_targeted():
    for group in sources.plan().groups:
        assert 1 <= len(group.domains) <= sources.DOMAINS_PER_SEARCH


def test_every_group_draws_only_on_verified_domains():
    allowed = set(sources.allowlist())
    for group in sources.plan().groups:
        assert set(group.domains) <= allowed


def test_the_allowlist_can_be_narrowed_to_one_tier():
    assert set(sources.allowlist(2)) == {s.domain for s in sources.plan().by_tier(2)}
    assert len(sources.allowlist()) == 100


def test_the_summary_states_the_zeroes():
    text = sources.summary()
    assert "100 verified-readable domains" in text
    assert "0 blocked, 0 YouTube, 0 X, 0 inaccessible" in text


def test_a_missing_file_degrades_quietly(tmp_path):
    assert sources.load(tmp_path / "nope.json") == []

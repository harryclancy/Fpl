"""The weekly source list, and what can actually be read from it.

The user curated ~165 sources. The useful question is not what is on the
list but what can be reached from where the research runs, and the answer
is narrower than the list looks: direct fetching is blocked by the egress
proxy, while a search scoped to a handful of domains returns their
article text. So the list is a search allowlist, not a fetch queue.

The thing these tests protect is honesty about the gap. A source that
cannot be read must be reported as unread rather than quietly dropped,
because "we checked 165 sources" is a much bigger claim than "we searched
80 domains and could not read the video and social ones".
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.research import sources


def test_the_curated_list_is_committed_and_loads():
    loaded = sources.load()
    assert len(loaded) >= 150, f"only {len(loaded)} sources committed"
    assert all(s.url.startswith("http") for s in loaded)


def test_it_covers_the_categories_a_week_actually_needs():
    categories = {s.category for s in sources.load()}
    for needed in ("Club team news RSS", "FPL specialist / rolling page",
                   "Premier League news / stats"):
        assert needed in categories, f"no {needed} sources"


def test_video_and_social_are_reported_as_unreadable_not_dropped():
    """A search cannot read a YouTube channel or an X profile. Claiming
    to have covered them would be the same class of dishonesty as an
    unattributed quote."""
    plan = sources.plan()

    domains = {s.domain for s in plan.unreachable}
    assert any("youtube.com" in d for d in domains)
    assert any("x.com" in d for d in domains)
    # And none of them leak into the searchable groups.
    searchable = {d for _, group in plan.groups for d in group}
    assert not any("youtube.com" in d for d in searchable)


def test_domains_are_deduplicated():
    """The list carries twenty Google News RSS URLs on one host. Searching
    that host twenty times returns the same results twenty times."""
    plan = sources.plan()
    flat = [d for _, group in plan.groups for d in group]
    assert len(flat) == len(set(flat))


def test_searches_are_grouped_small_enough_to_be_useful():
    for category, group in sources.plan().groups:
        assert 1 <= len(group) <= sources.DOMAINS_PER_SEARCH


def test_team_news_is_worked_before_tactical_reads():
    """Team news invalidates everything else — a tactical read on a player
    who has just been ruled out is wasted effort."""
    categories = [category for category, _ in sources.plan().groups]
    if "Club team news RSS" in categories and "Podcast / video" in categories:
        assert categories.index("Club team news RSS") < categories.index("Podcast / video")


def test_a_missing_file_degrades_quietly(tmp_path):
    assert sources.load(tmp_path / "nope.json") == []


def test_the_summary_states_the_gap_not_just_the_reach():
    text = sources.summary()
    assert "searchable domains" in text
    assert "cannot read" in text

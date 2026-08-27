"""Whether a recommendation is backed by research or by arithmetic.

A player with five outlets behind him and one nobody has written about
look identical in a squad list — one just has more text underneath. That's
the same failure as "weighed and rejected" looking like "never
considered": the reader can't tell which they're seeing, so they can't
calibrate how much to trust it.

None of these levels is bad. Numbers-only is fine for a sixth-choice bench
defender and thin for the armband, and the difference belongs on the page
rather than in the reader's assumptions.
"""
import pandas as pd

from fpl_assistant.analysis import provenance


def _row(**overrides) -> pd.Series:
    return pd.Series({"consensus_tier": None, "consensus_gameweek": pd.NA, **overrides})


def test_research_from_this_gameweek_reads_as_fresh():
    mark = provenance.for_player(_row(consensus_tier="strong", consensus_gameweek=3), gameweek=3)
    assert mark.level == provenance.FRESH
    assert "this gameweek" in mark.label


def test_research_from_an_earlier_gameweek_reads_as_stale():
    mark = provenance.for_player(_row(consensus_tier="strong", consensus_gameweek=1), gameweek=4)
    assert mark.level == provenance.STALE
    assert "re-check" in mark.label
    assert "move fast" in mark.blurb


def test_no_research_reads_as_numbers_only():
    mark = provenance.for_player(_row(), gameweek=3)
    assert mark.level == provenance.NUMBERS
    assert "No analyst coverage" in mark.blurb


def test_an_undated_annotation_is_treated_as_current():
    """Older files didn't stamp a gameweek, and the annotation only loads
    from the current gameweek's file anyway — so unknown means current,
    not stale."""
    mark = provenance.for_player(_row(consensus_tier="value"), gameweek=2)
    assert mark.level == provenance.FRESH


def test_an_empty_tier_string_is_not_research():
    assert provenance.for_player(_row(consensus_tier=""), gameweek=2).level == provenance.NUMBERS


def test_every_level_has_an_icon_a_label_and_an_explanation():
    """These are rendered straight onto the page; a missing one would show
    as a blank chip."""
    for level in (provenance.FRESH, provenance.STALE, provenance.NUMBERS):
        mark = provenance.Provenance(level)
        assert mark.icon and mark.label and mark.blurb


def test_summarise_counts_a_squad_by_backing():
    scored = pd.DataFrame([
        {"id": 1, "consensus_tier": "strong", "consensus_gameweek": 3},
        {"id": 2, "consensus_tier": "value", "consensus_gameweek": 1},
        {"id": 3, "consensus_tier": None, "consensus_gameweek": pd.NA},
    ]).set_index("id", drop=False)

    counts = provenance.summarise(scored, [1, 2, 3], gameweek=3)
    assert counts == {provenance.FRESH: 1, provenance.STALE: 1, provenance.NUMBERS: 1}


def test_a_player_missing_from_the_pool_counts_as_numbers_only():
    """Not an error — an unknown player is simply unbacked."""
    scored = pd.DataFrame([{"id": 1, "consensus_tier": "strong", "consensus_gameweek": 2}]).set_index("id", drop=False)
    assert provenance.summarise(scored, [1, 99], gameweek=2)[provenance.NUMBERS] == 1

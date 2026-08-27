"""Which players a week's decisions could actually involve.

This exists because research coverage used to be decided by the FPL media
cycle: search for who analysts were discussing, write those down, end up
with a dozen entries out of a seven-hundred-player pool — and sometimes
miss a player the model itself wanted to recommend.

Coverage should be driven by need. The tests below pin down what "need"
means: your squad, the moves you could actually afford, the template, and
whatever the projection rates highly.
"""
import pandas as pd
import pytest

from fpl_assistant.analysis import decision_set

BASE = {
    "team_short_name": "AAA", "status": "a", "selected_by_percent": 2.0,
    "xp_horizon": 10.0,
}


def _pool(*rows) -> pd.DataFrame:
    built = []
    for i, row in enumerate(rows, start=1):
        entry = {**BASE, **row}
        entry["id"] = i
        entry.setdefault("web_name", f"P{i}")
        entry.setdefault("position", "MID")
        entry.setdefault("price", 6.0)
        built.append(entry)
    return pd.DataFrame(built).set_index("id", drop=False)


def _named(result, name):
    return next((e for e in result.entries if e.name == name), None)


# --- what gets in --------------------------------------------------------

def test_your_own_squad_is_always_included():
    """You will hold, bench or sell every one of them, so every one is a
    decision."""
    pool = _pool({"web_name": "Mine", "xp_horizon": 1.0}, {"web_name": "Other"})
    result = decision_set.build(pool, owned_ids=[1])

    assert _named(result, "Mine") is not None
    assert "in your squad" in _named(result, "Mine").reasons


def test_the_template_is_included_even_if_you_would_never_buy_him():
    """Not owning a widely-owned player is itself a position."""
    pool = _pool({"web_name": "Popular", "selected_by_percent": 55.0, "xp_horizon": 1.0})
    entry = _named(decision_set.build(pool), "Popular")

    assert entry is not None
    assert "not owning him is a position" in " ".join(entry.reasons)


def test_a_player_the_model_rates_is_included_whether_or_not_anyone_wrote_about_him():
    """The recommendations that most need something behind them."""
    rows = [{"web_name": f"Filler{i}", "xp_horizon": 5.0} for i in range(30)]
    rows.append({"web_name": "ModelPick", "xp_horizon": 90.0})
    entry = _named(decision_set.build(_pool(*rows)), "ModelPick")

    assert entry is not None
    assert "projection rates him highly" in " ".join(entry.reasons)


def test_transfer_targets_are_limited_to_what_you_could_actually_afford():
    """Judged against the cheapest player you own in that position plus
    the bank — the money a like-for-like swap really has. Against whole
    squad value it would sweep in premiums no single transfer reaches."""
    pool = _pool(
        {"web_name": "MyCheapMid", "price": 5.0, "xp_horizon": 5.0},
        {"web_name": "Affordable", "price": 5.5, "xp_horizon": 30.0},
        {"web_name": "Unreachable", "price": 13.0, "xp_horizon": 99.0},
    )
    result = decision_set.build(pool, owned_ids=[1], bank=1.0)

    assert _named(result, "Affordable") is not None
    reachable = _named(result, "Unreachable")
    # He may still appear as a model favourite, but never as a target.
    if reachable is not None:
        assert not any("target at this budget" in r for r in reachable.reasons)


def test_a_bigger_bank_reaches_further():
    pool = _pool(
        {"web_name": "MyCheapMid", "price": 5.0, "xp_horizon": 5.0},
        {"web_name": "Pricey", "price": 9.0, "xp_horizon": 40.0},
    )
    poor = decision_set.build(pool, owned_ids=[1], bank=0.0)
    rich = decision_set.build(pool, owned_ids=[1], bank=5.0)

    assert not any("target at this budget" in r for r in (_named(poor, "Pricey").reasons if _named(poor, "Pricey") else []))
    assert any("target at this budget" in r for r in _named(rich, "Pricey").reasons)


def test_unavailable_players_are_excluded():
    pool = _pool({"web_name": "Injured", "status": "i", "selected_by_percent": 60.0})
    assert _named(decision_set.build(pool), "Injured") is None


def test_an_empty_pool_is_handled():
    """Regression: `.get("status", "a") == "a"` on an empty frame yields a
    bare True, which pandas then treats as a column label. Same trap as
    the projection's optional-column reads."""
    assert len(decision_set.build(pd.DataFrame())) == 0


def test_a_pool_with_no_status_column_is_handled():
    pool = pd.DataFrame([
        {"id": 1, "web_name": "X", "position": "MID", "price": 6.0,
         "selected_by_percent": 40.0, "xp_horizon": 10.0, "team_short_name": "AAA"}
    ]).set_index("id", drop=False)
    assert len(decision_set.build(pool)) == 1


# --- how deep ------------------------------------------------------------

def test_a_transfer_target_needs_the_full_treatment():
    pool = _pool(
        {"web_name": "Mine", "price": 5.5, "xp_horizon": 5.0},
        {"web_name": "Target", "price": 5.5, "xp_horizon": 40.0},
    )
    target = _named(decision_set.build(pool, owned_ids=[1]), "Target")
    assert target.depth == decision_set.DEPTH_FULL


def test_a_squad_filler_needs_facts_not_an_essay():
    """Writing a case for someone you'll never start is effort spent where
    no decision is being made."""
    pool = _pool({"web_name": "Bench", "xp_horizon": 1.0, "selected_by_percent": 0.2})
    entry = _named(decision_set.build(pool, owned_ids=[1]), "Bench")

    assert entry.depth == decision_set.DEPTH_FACTS
    assert not entry.needs_writing_up


def test_the_full_treatment_players_are_listed_first():
    pool = _pool(
        {"web_name": "Filler", "xp_horizon": 1.0},
        {"web_name": "Popular", "selected_by_percent": 60.0, "xp_horizon": 2.0},
    )
    result = decision_set.build(pool, owned_ids=[1])
    assert result.entries[0].depth == decision_set.DEPTH_FULL


def test_a_player_can_qualify_for_more_than_one_reason():
    pool = _pool({"web_name": "Star", "selected_by_percent": 60.0, "xp_horizon": 50.0})
    reasons = _named(decision_set.build(pool, owned_ids=[1]), "Star").reasons
    assert len(reasons) >= 2


# --- coverage ------------------------------------------------------------

def test_coverage_reports_what_is_missing_research():
    """The honest measure of whether the app's advice is informed or
    merely computed."""
    pool = _pool(
        {"web_name": "Researched", "selected_by_percent": 60.0, "consensus_tier": "strong"},
        {"web_name": "Bare", "selected_by_percent": 55.0, "consensus_tier": None},
    )
    result = decision_set.build(pool)
    report = decision_set.coverage(result, pool)

    assert report["total"] == 2
    assert report["researched"] == 1
    assert report["share"] == pytest.approx(0.5)
    assert [e.name for e in report["missing"]] == ["Bare"]


def test_full_coverage_reports_as_full():
    pool = _pool({"web_name": "A", "selected_by_percent": 60.0, "consensus_tier": "strong"})
    result = decision_set.build(pool)
    assert decision_set.coverage(result, pool)["share"] == 1.0


def test_coverage_of_an_empty_set_does_not_divide_by_zero():
    assert decision_set.coverage(decision_set.DecisionSet(), pd.DataFrame())["share"] == 1.0

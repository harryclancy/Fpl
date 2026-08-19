"""Tests for chip timing, price pressure, and the roll-vs-use decision.

Chips are the largest points lever in the game and the one most often
wasted — a chip played into a random gameweek is worth close to nothing,
so every test here is really about whether the advice keys off the
schedule rather than off vibes.
"""
import pandas as pd
import pytest

from fpl_assistant.analysis import chips, optimiser, price
from tests.test_optimiser import _pool


@pytest.fixture
def pool_and_solution():
    pool = _pool()
    solution = optimiser.optimise_squad(pool, budget=100.0)
    return pool, solution


def _fixtures(double_gw: int | None = None, blank_team: int | None = None, n: int = 5):
    """Round-robin fixtures, optionally with a double or a blank injected."""
    rows = []
    teams = list(range(1, 21))
    for gw in range(1, n + 1):
        for i in range(0, 20, 2):
            home, away = teams[i], teams[i + 1]
            if blank_team is not None and gw == 2 and blank_team in (home, away):
                continue
            rows.append({"event": gw, "team_h": home, "team_a": away,
                         "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": False})
        if double_gw is not None and gw == double_gw:
            rows.append({"event": gw, "team_h": 1, "team_a": 3,
                         "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": False})
    return pd.DataFrame(rows)


def _with_gameweek_points(pool: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """Attach per-gameweek projections, which chip advice reads."""
    pool = pool.copy()
    for gw in range(1, n + 1):
        pool[f"xp_gw{gw}"] = pool["xp_next"]
    return pool


# --- Fixture counting ---------------------------------------------------

def test_fixture_counts_identify_doubles_and_blanks():
    counts = chips.gameweek_fixture_counts(_fixtures(double_gw=3, blank_team=5), 1, 5)
    assert counts.loc[1, 3] == 2, "team 1 should have a double in GW3"
    assert counts.loc[5, 2] == 0, "team 5 should blank in GW2"
    assert counts.loc[2, 1] == 1


# --- Triple Captain -----------------------------------------------------

def test_triple_captain_picks_the_best_gameweek():
    pool = _pool()
    solution = optimiser.optimise_squad(pool, budget=100.0)
    scored = _with_gameweek_points(pool)
    # Make GW4 clearly the best week for everyone.
    scored["xp_gw4"] = scored["xp_next"] * 2

    counts = chips.gameweek_fixture_counts(_fixtures(), 1, 5)
    advice = chips.advise_triple_captain(scored, solution.squad_ids, counts, 1, 5)

    assert advice.gameweek == 4
    assert advice.chip == "Triple Captain"
    assert "GW4" in advice.recommendation


def test_triple_captain_flags_a_double_gameweek_as_urgent():
    pool = _pool()
    solution = optimiser.optimise_squad(pool, budget=100.0)
    scored = _with_gameweek_points(pool)
    # Team 1 doubles in GW3; make one of its players the standout.
    scored.loc[scored["team"] == 1, "xp_gw3"] = 20.0
    squad_with_team1 = list(set(solution.squad_ids) | set(scored[scored["team"] == 1]["id"].head(1)))

    counts = chips.gameweek_fixture_counts(_fixtures(double_gw=3), 1, 5)
    advice = chips.advise_triple_captain(scored, squad_with_team1, counts, 1, 5)

    assert advice.gameweek == 3
    assert advice.urgent, "a double gameweek is exactly when this chip should be played"
    assert any("double gameweek" in line for line in advice.detail)


# --- Bench Boost --------------------------------------------------------

def test_bench_boost_holds_when_the_bench_is_weak():
    """A good squad has a cheap bench, which is the wrong bench for this
    chip — the advice must say so rather than recommending it anyway."""
    pool = _pool()
    solution = optimiser.optimise_squad(pool, budget=100.0)
    scored = _with_gameweek_points(pool)
    scored.loc[scored["id"].isin(solution.bench_ids), [f"xp_gw{g}" for g in range(1, 6)]] = 1.0

    advice = chips.advise_bench_boost(
        scored, solution.bench_ids, chips.gameweek_fixture_counts(_fixtures(), 1, 5), 1, 5
    )
    assert not advice.urgent
    assert any("below the" in line.lower() for line in advice.detail)


def test_bench_boost_recommends_a_strong_bench_week():
    pool = _pool()
    solution = optimiser.optimise_squad(pool, budget=100.0)
    scored = _with_gameweek_points(pool)
    scored.loc[scored["id"].isin(solution.bench_ids), "xp_gw3"] = 8.0

    advice = chips.advise_bench_boost(
        scored, solution.bench_ids, chips.gameweek_fixture_counts(_fixtures(), 1, 5), 1, 5
    )
    assert advice.gameweek == 3
    assert advice.urgent


# --- Free Hit -----------------------------------------------------------

def test_free_hit_holds_when_nothing_blanks():
    pool = _pool()
    solution = optimiser.optimise_squad(pool, budget=100.0)
    scored = _with_gameweek_points(pool)

    advice = chips.advise_free_hit(
        scored, solution.squad_ids, chips.gameweek_fixture_counts(_fixtures(), 1, 5), 1, 5
    )
    assert "Hold" in advice.recommendation
    assert not advice.urgent


def test_free_hit_flags_a_gameweek_where_the_squad_blanks():
    pool = _pool()
    scored = _with_gameweek_points(pool)
    # Build a squad concentrated in teams that blank in GW2.
    blanking = scored[scored["team"].isin([5, 6])]["id"].tolist()[:15]
    counts = chips.gameweek_fixture_counts(_fixtures(blank_team=5), 1, 5)

    advice = chips.advise_free_hit(scored, blanking, counts, 1, 5)
    assert advice.gameweek == 2
    assert advice.value and advice.value > 0


# --- Wildcard -----------------------------------------------------------

def test_wildcard_holds_when_the_squad_is_already_optimal():
    pool = _pool()
    solution = optimiser.optimise_squad(pool, budget=100.0)
    advice = chips.advise_wildcard(pool, solution.squad_ids, budget=100.0)

    assert "Hold" in advice.recommendation
    assert not advice.urgent


def test_wildcard_recommended_when_the_squad_is_far_behind():
    """The honest test is re-solving and measuring the gap, not a feeling
    about the team."""
    pool = _pool()
    # A deliberately poor squad: the cheapest legal fifteen.
    poor = []
    for position, quota in optimiser.SQUAD_QUOTAS.items():
        poor += pool[pool["position"] == position].nsmallest(quota, "xp_horizon")["id"].tolist()

    advice = chips.advise_wildcard(pool, poor, budget=100.0)
    assert advice.value > chips.WILDCARD_GAIN_THRESHOLD
    assert advice.urgent


def test_advise_all_returns_every_chip_urgent_first():
    pool = _pool()
    solution = optimiser.optimise_squad(pool, budget=100.0)
    scored = _with_gameweek_points(pool)

    advice = chips.advise_all(scored, solution, _fixtures(), from_event=1, lookahead=5)
    assert {a.chip for a in advice} == {"Triple Captain", "Bench Boost", "Free Hit", "Wildcard"}
    urgency = [a.urgent for a in advice]
    assert urgency == sorted(urgency, reverse=True), "urgent advice should sort first"


# --- Price pressure -----------------------------------------------------

def _price_frame(rows):
    return pd.DataFrame(rows).set_index("id", drop=False)


def test_price_pressure_scales_with_ownership():
    """The same net transfers mean far more for a lightly-owned player —
    that's why raw transfer counts are the wrong signal."""
    df = price.price_pressure(_price_frame([
        {"id": 1, "web_name": "Low", "selected_by_percent": 1.0,
         "transfers_in_event": 60000, "transfers_out_event": 0},
        {"id": 2, "web_name": "High", "selected_by_percent": 40.0,
         "transfers_in_event": 60000, "transfers_out_event": 0},
    ]))
    assert df.loc[1, "price_pressure"] > df.loc[2, "price_pressure"]
    assert df.loc[1, "price_signal"] == "rising"


def test_heavy_outflow_signals_a_fall():
    df = price.price_pressure(_price_frame([
        {"id": 1, "web_name": "Out", "selected_by_percent": 5.0,
         "transfers_in_event": 0, "transfers_out_event": 200000},
    ]))
    assert df.loc[1, "price_signal"] == "falling"
    assert df.loc[1, "net_transfers"] < 0


def test_barely_owned_players_are_not_signalled():
    """A player owned by 0.1% can double their transfers on a rumour, so
    the ratio is noise rather than signal."""
    df = price.price_pressure(_price_frame([
        {"id": 1, "web_name": "Obscure", "selected_by_percent": 0.1,
         "transfers_in_event": 5000, "transfers_out_event": 0},
    ]))
    assert df.loc[1, "price_signal"] == "stable"


def test_unowned_player_does_not_divide_by_zero():
    df = price.price_pressure(_price_frame([
        {"id": 1, "web_name": "Nobody", "selected_by_percent": 0.0,
         "transfers_in_event": 100, "transfers_out_event": 0},
    ]))
    assert df.loc[1, "price_pressure"] == 0.0
    assert df.loc[1, "price_signal"] == "stable"


def test_price_note_says_what_to_do_not_just_what_happened():
    df = price.price_pressure(_price_frame([
        {"id": 1, "web_name": "Riser", "selected_by_percent": 5.0,
         "transfers_in_event": 200000, "transfers_out_event": 0},
    ]))
    note = price.price_note(df.loc[1])
    assert note and "rising" in note.lower()
    assert "buying" in note.lower()


def test_stable_player_gets_no_note():
    df = price.price_pressure(_price_frame([
        {"id": 1, "web_name": "Steady", "selected_by_percent": 10.0,
         "transfers_in_event": 100, "transfers_out_event": 90},
    ]))
    assert price.price_note(df.loc[1]) is None


# --- Roll vs use --------------------------------------------------------

def test_roll_decision_returns_both_sides_of_the_trade(pool_and_solution):
    pool, solution = pool_and_solution
    decision = optimiser.should_roll_transfer(pool, solution.squad_ids, bank=2.0, free_transfers=1)

    assert decision.recommendation in {"Roll it", "Use it now"}
    assert decision.detail
    assert decision.roll_gain >= 0


def test_optimal_squad_with_nothing_to_do_rolls(pool_and_solution):
    pool, solution = pool_and_solution
    decision = optimiser.should_roll_transfer(pool, solution.squad_ids, bank=0.0, free_transfers=1)
    assert decision.recommendation == "Roll it"


def test_unpublished_gameweeks_are_not_treated_as_blanks():
    """A gameweek where *nobody* has a fixture isn't a blank — it's one the
    fixture list doesn't cover yet. Conflating the two made Free Hit
    announce that all fifteen of your players blank, every week past the
    end of the published schedule."""
    counts = chips.gameweek_fixture_counts(_fixtures(n=3), from_event=1, lookahead=8)
    assert list(counts.columns) == [1, 2, 3], "only scheduled gameweeks should appear"


def test_free_hit_ignores_gameweeks_beyond_the_schedule():
    pool = _pool()
    scored = _with_gameweek_points(pool)
    solution = optimiser.optimise_squad(pool, budget=100.0)

    advice = chips.advise_free_hit(
        scored, solution.squad_ids,
        chips.gameweek_fixture_counts(_fixtures(n=3), 1, 8), 1, 8,
    )
    assert "Hold" in advice.recommendation
    assert not advice.urgent


def test_wildcard_wording_avoids_negative_zero():
    pool = _pool()
    solution = optimiser.optimise_squad(pool, budget=100.0)
    advice = chips.advise_wildcard(pool, solution.squad_ids, budget=100.0)
    assert "-0" not in advice.recommendation

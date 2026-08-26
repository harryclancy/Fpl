"""Tests for the natural-language question router.

Name detection gets the most attention: a router that matches "captain" to
a player called Cap, or "the" to Theo, answers a question nobody asked and
looks authoritative doing it. Every test here goes through the real free
engine — no LLM — because that path has to work with no API key at all.
"""
import pandas as pd
import pytest

from fpl_assistant.analysis import ask, optimiser
from tests.test_optimiser import _pool


@pytest.fixture
def pool_and_solution():
    pool = _pool()
    # Give the pool realistic name fields; _pool() only sets web_name.
    pool = pool.copy()
    pool["second_name"] = pool["web_name"]
    pool["first_name"] = "A"
    solution = optimiser.optimise_squad(pool, budget=100.0)
    return pool, solution


def _named(pool, name, position="MID"):
    """Rename one player so questions can refer to them by a real name."""
    pool = pool.copy()
    target = pool[pool["position"] == position]["id"].iloc[0]
    pool.loc[pool["id"] == target, "web_name"] = name
    pool.loc[pool["id"] == target, "second_name"] = name
    return pool, int(target)


def test_finds_a_player_named_in_the_question(pool_and_solution):
    pool, _ = pool_and_solution
    pool, target = _named(pool, "Fernandes")

    assert ask.find_players("why no Fernandes?", pool)[0] == target


def test_ignores_question_words_that_look_like_names(pool_and_solution):
    """"Who should I captain?" must not match a player on a stopword —
    the router would confidently answer about the wrong person."""
    pool, _ = pool_and_solution
    pool, _ = _named(pool, "Captain")

    assert ask.find_players("who should I captain?", pool) == []


def test_why_not_question_returns_the_counterfactual(pool_and_solution):
    pool, solution = pool_and_solution
    outside = pool[~pool["id"].isin(solution.squad_ids)]
    name = "Fernandes"
    pool = pool.copy()
    target = int(outside["id"].iloc[0])
    pool.loc[pool["id"] == target, ["web_name", "second_name"]] = name

    result = ask.answer_locally("why no Fernandes?", pool, solution)
    assert result is not None
    assert not result.in_squad
    assert result.points_delta is not None


def test_or_question_is_treated_as_a_comparison(pool_and_solution):
    pool, solution = pool_and_solution
    pool = pool.copy()
    ids = pool["id"].tolist()[:2]
    pool.loc[pool["id"] == ids[0], ["web_name", "second_name"]] = "Salah"
    pool.loc[pool["id"] == ids[1], ["web_name", "second_name"]] = "Palmer"

    result = ask.answer_locally("Salah or Palmer?", pool, solution)
    assert result is not None
    assert "Salah" in result.player_name and "Palmer" in result.player_name


def test_captain_question_answers_about_the_armband(pool_and_solution):
    pool, solution = pool_and_solution
    result = ask.answer_locally("who should I captain this week?", pool, solution)

    assert result is not None
    assert "Captain" in result.headline
    captain_name = pool.set_index("id").loc[solution.captain_id, "web_name"]
    assert captain_name in result.headline


def test_best_value_question_returns_a_leaderboard(pool_and_solution):
    pool, solution = pool_and_solution
    pool = pool.copy()
    pool["xp_per_million"] = pool["xp_horizon"] / pool["price"]

    result = ask.answer_locally("best value midfielder?", pool, solution)
    assert result is not None
    assert "value" in result.headline.lower()
    assert result.detail


def test_position_question_filters_to_that_position(pool_and_solution):
    pool, solution = pool_and_solution
    result = ask.answer_locally("best defender?", pool, solution)

    assert result is not None
    names = " ".join(result.detail)
    defenders = set(pool[pool["position"] == "DEF"]["web_name"])
    assert any(name in names for name in defenders)


def test_differential_question_excludes_highly_owned(pool_and_solution):
    pool, solution = pool_and_solution
    pool = pool.copy()
    pool["selected_by_percent"] = 50.0
    cheap = pool["id"].tolist()[:3]
    pool.loc[pool["id"].isin(cheap), "selected_by_percent"] = 2.0

    result = ask.answer_locally("any good differentials?", pool, solution)
    assert result is not None
    low_owned = set(pool[pool["selected_by_percent"] < 10]["web_name"])
    assert any(name in " ".join(result.detail) for name in low_owned)


def test_unparseable_question_returns_none(pool_and_solution):
    """Questions needing judgement must fall through rather than being
    answered badly by pattern-matching."""
    pool, solution = pool_and_solution
    assert ask.answer_locally("is the manager going to rotate after Europe?", pool, solution) is None


def test_an_unanswerable_question_comes_back_with_the_briefing_attached(pool_and_solution):
    """Nothing here calls a paid API. A question the engine can't handle
    is handed back ready to paste into a chat, with the squad briefing
    included so the answer on the other side isn't guessing about who is
    actually in the team."""
    pool, solution = pool_and_solution
    result = ask.ask("will there be a shock team announcement?", pool, solution, 1)

    assert result.source == "unanswered"
    assert result.note
    assert result.text, "the briefing should travel with the question"
    captain_name = pool.set_index("id").loc[solution.captain_id, "web_name"]
    assert captain_name in result.text


def test_a_recognised_question_is_answered_from_the_numbers(pool_and_solution):
    pool, solution = pool_and_solution
    assert ask.ask("who should I captain?", pool, solution, 1).source == "engine"


def test_there_is_no_paid_code_path_left():
    """The guarantee the owner asked for: the app cannot spend money.

    The metered fallback was removed rather than disabled, because a
    disabled path is one config change away from being a live one — and
    the spend it caused was invisible and per-question.
    """
    import inspect

    source = inspect.getsource(ask)
    assert "anthropic" not in source.lower()
    assert "api_key" not in source
    assert not hasattr(ask, "answer_with_claude")
    assert not hasattr(ask, "claude_available")


def test_squad_context_names_the_actual_squad(pool_and_solution):
    """The briefing is what stops Claude contradicting the app about who
    is in the squad."""
    pool, solution = pool_and_solution
    context = ask.squad_context(pool, solution, next_event=1)

    captain_name = pool.set_index("id").loc[solution.captain_id, "web_name"]
    assert captain_name in context
    assert "Starting XI" in context and "Bench" in context
    for player_id in solution.starting_ids:
        assert str(pool.set_index("id").loc[player_id, "web_name"]) in context

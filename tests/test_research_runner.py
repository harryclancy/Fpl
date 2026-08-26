"""The scheduled researcher's decision logic.

The API isn't reachable from this environment, so the agent itself is
stubbed and what's tested is everything around it: when to research, when
to stay quiet, and — the part that matters — what happens when the
research comes back bad.

That last one is the whole safety property. An agent that writes something
plausible for every field every time will eventually write something
plausible and wrong, and the app has no way to tell. Rejecting it and
keeping last week's file is the only honest response.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.research_gameweek as runner
from fpl_assistant.research.agent import ResearchResult


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    """Never let a test write into the real research directories."""
    consensus_dir = tmp_path / "consensus"
    odds_dir = tmp_path / "odds"
    consensus_dir.mkdir()
    odds_dir.mkdir()
    monkeypatch.setattr(runner, "CONSENSUS_DIR", consensus_dir)
    monkeypatch.setattr(runner, "ODDS_DIR", odds_dir)
    return consensus_dir, odds_dir


@pytest.fixture
def api_at(monkeypatch):
    """Puts the season a given number of hours before GW1's deadline."""
    import tests.test_app_smoke as smoke
    from fpl_assistant import api

    def _apply(hours_to_deadline: float):
        bootstrap = smoke._synthetic_bootstrap(preseason=True)
        now = datetime.now(timezone.utc)
        for offset, event in enumerate(bootstrap["events"]):
            event["deadline_time"] = (
                now + timedelta(hours=hours_to_deadline) + timedelta(days=7 * offset)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            event["finished"] = False
        monkeypatch.setattr(api, "get_bootstrap_static", lambda: bootstrap)
        monkeypatch.setattr(api, "get_fixtures", lambda event=None: smoke._synthetic_fixtures())

    return _apply


def _stub(monkeypatch, players: ResearchResult, odds: ResearchResult):
    monkeypatch.setattr(runner.agent, "research_players", lambda *a, **k: players)
    monkeypatch.setattr(runner.agent, "research_odds", lambda *a, **k: odds)


def _good_players():
    return ResearchResult("players", {"gameweek": 1, "researched": "2026-08-19",
                                      "players": [{"name": "Haaland"}]}, [], searches=9)


def _good_odds():
    return ResearchResult("odds", {"gameweek": 1, "researched": "2026-08-19",
                                   "players": [{"name": "Haaland"}], "matchups": []}, [], searches=6)


# --- when to run --------------------------------------------------------

def test_it_researches_close_to_the_deadline(api_at, monkeypatch, sandbox):
    api_at(24)
    _stub(monkeypatch, _good_players(), _good_odds())

    assert runner.main() == 0
    consensus_dir, odds_dir = sandbox
    assert (consensus_dir / "gw1.json").exists()
    assert (odds_dir / "gw1.json").exists()


def test_it_stays_quiet_when_the_deadline_is_far_off(api_at, monkeypatch, sandbox):
    """Research done a fortnight out is refreshed with the same
    uncertainty it already had, and costs an API call to produce."""
    api_at(500)
    _stub(monkeypatch, _good_players(), _good_odds())

    assert runner.main() == 0
    assert not list(sandbox[0].glob("*.json"))


def test_it_refuses_once_the_deadline_has_passed(api_at, monkeypatch, sandbox):
    api_at(-2)
    _stub(monkeypatch, _good_players(), _good_odds())

    assert runner.main() == 0
    assert not list(sandbox[0].glob("*.json"))


# --- what lands ---------------------------------------------------------

def test_the_written_file_carries_the_explanatory_note(api_at, monkeypatch, sandbox):
    """The note explains what each field is for. An agent won't write it,
    and without it the file is unreadable to the next person."""
    api_at(24)
    _stub(monkeypatch, _good_players(), _good_odds())
    runner.main()

    written = json.loads((sandbox[0] / "gw1.json").read_text())
    assert "watch_out" in written["note"]
    assert written["season"] == "2026/27"


# --- rejection ----------------------------------------------------------

def test_failed_research_is_not_written(api_at, monkeypatch, sandbox):
    """The safety property. Plausible-but-unsupported is the failure mode
    that actually reaches users."""
    api_at(24)
    _stub(
        monkeypatch,
        ResearchResult("players", {"players": []}, ["no counter-argument for Haaland"]),
        _good_odds(),
    )

    assert runner.main() == 1
    assert not (sandbox[0] / "gw1.json").exists()
    assert (sandbox[1] / "gw1.json").exists(), "a good odds file should still land"


def test_failed_research_leaves_the_previous_file_untouched(api_at, monkeypatch, sandbox):
    """Stale research known to be stale beats fresh research that's
    wrong."""
    api_at(24)
    existing = {"gameweek": 1, "researched": "2026-08-12", "players": [{"name": "LastWeek"}]}
    (sandbox[0] / "gw1.json").write_text(json.dumps(existing))

    _stub(monkeypatch, ResearchResult("players", None, ["the API call failed"]), _good_odds())
    assert runner.main() == 1

    kept = json.loads((sandbox[0] / "gw1.json").read_text())
    assert kept["players"][0]["name"] == "LastWeek"


def test_a_failure_in_one_half_does_not_block_the_other(api_at, monkeypatch, sandbox):
    api_at(24)
    _stub(monkeypatch, _good_players(), ResearchResult("odds", None, ["no odds pages found"]))

    assert runner.main() == 1
    assert (sandbox[0] / "gw1.json").exists()
    assert not (sandbox[1] / "gw1.json").exists()


# --- the prompt gets the real fixtures ----------------------------------

def test_the_agent_is_told_which_matches_are_actually_being_played(api_at, monkeypatch, sandbox):
    """Without the fixture list the agent researches whichever games it
    remembers, which for a matchup note is worse than useless."""
    api_at(24)
    captured = {}

    def _capture(gameweek, today, fixtures=""):
        captured["fixtures"] = fixtures
        return _good_odds()

    monkeypatch.setattr(runner.agent, "research_players", lambda *a, **k: _good_players())
    monkeypatch.setattr(runner.agent, "research_odds", _capture)
    runner.main()

    assert "GW1 fixtures are" in captured["fixtures"]
    assert " v " in captured["fixtures"]


# --- failures that actually happened ------------------------------------

def test_a_truncated_answer_is_named_as_truncation():
    """The first live run hit the output ceiling partway through a string
    and surfaced as "Unterminated string at column 45982" — which sends
    you hunting for a schema bug when the answer was simply cut off."""
    from fpl_assistant.research import agent

    class _Response:
        stop_reason = "max_tokens"
        content = []

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_final_message(self):
            return _Response()

    class _Client:
        class messages:
            @staticmethod
            def stream(**kwargs):
                return _Stream()

    agent_client = agent._client
    agent._client = lambda: _Client()
    try:
        with pytest.raises(RuntimeError, match="cut off"):
            agent._ask("anything", {"type": "object"})
    finally:
        agent._client = agent_client


def test_a_billing_failure_reads_as_a_billing_failure():
    """It arrived as a raw error dict, which reads like a bug in the
    request. It isn't, and the fix is somewhere else entirely."""
    from fpl_assistant.research import agent

    raw = (
        "{'type': 'error', 'error': {'type': 'invalid_request_error', 'message': "
        "'Your credit balance is too low to access the Anthropic API.'}}"
    )
    message = agent._readable(RuntimeError(raw))
    assert "Out of Anthropic API credit" in message
    assert "console.anthropic.com" in message


def test_a_rejected_key_reads_as_a_key_problem():
    from fpl_assistant.research import agent

    message = agent._readable(RuntimeError("authentication_error: invalid x-api-key"))
    assert "ANTHROPIC_API_KEY repository secret" in message


def test_an_unrecognised_error_is_passed_through_unchanged():
    """Don't dress up a failure we don't understand as one we do."""
    from fpl_assistant.research import agent

    assert agent._readable(RuntimeError("something new")) == "something new"

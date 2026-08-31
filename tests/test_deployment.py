"""The deployment and freshness machinery.

The user's complaint was operational: after Claude Code changed something
they were opening the Streamlit dashboard and pressing Reboot. Streamlit
Community Cloud already redeploys automatically on push, so the reboot was
never fixing a deploy — it was answering a question the app refused to
answer, namely "is the new version actually live?"

These tests cover the two halves of the answer: a visible build marker, and
a research-staleness check that distinguishes live data (always current)
from committed research (which can belong to a previous gameweek).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant import version
from fpl_assistant.analysis import freshness


# --- the build marker ----------------------------------------------------

def test_the_deployed_commit_is_readable_without_shelling_out():
    """Streamlit Cloud clones the repo but does not guarantee `git` on
    PATH, so this reads .git directly. A version marker that throws is
    worse than none."""
    current = version.current()

    assert current.known
    assert len(current.commit) == 40
    assert len(current.short) == 7
    assert current.short in current.display


def test_a_missing_git_directory_degrades_to_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(version, "GIT_DIR", tmp_path / "nope")
    current = version.current()

    assert not current.known
    assert current.display == "version unknown"


def test_an_environment_commit_wins_over_the_git_directory(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "a" * 40)
    assert version.current().short == "aaaaaaa"


def test_a_packed_ref_is_still_resolved(monkeypatch, tmp_path):
    """A fresh clone — which is exactly what a Streamlit deploy is — keeps
    refs packed rather than as loose files."""
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "packed-refs").write_text(f"# pack-refs\n{'b' * 40} refs/heads/main\n")
    monkeypatch.setattr(version, "GIT_DIR", git)
    monkeypatch.delenv("GIT_COMMIT", raising=False)

    current = version.current()
    assert current.short == "bbbbbbb"
    assert current.branch == "main"


# --- research staleness --------------------------------------------------

def test_research_for_the_current_gameweek_is_fresh():
    from datetime import datetime, timezone
    state = freshness.check(gameweek=3, research_gameweek=3,
                            researched_at=datetime.now(timezone.utc).isoformat())
    assert state.state == freshness.FRESH
    assert state.message == ""


def test_research_from_a_previous_gameweek_is_stale_however_recent():
    """A file written an hour ago for the wrong gameweek is wrong. Team
    news does not survive a deadline."""
    from datetime import datetime, timezone
    just_now = datetime.now(timezone.utc).isoformat()

    state = freshness.check(gameweek=3, research_gameweek=2, researched_at=just_now)

    assert state.stale
    assert "from Gameweek 2, not Gameweek 3" in state.message
    assert "team news does not survive a deadline" in state.message


def test_missing_research_is_reported_rather_than_hidden():
    state = freshness.check(gameweek=3, research_gameweek=None)
    assert state.stale
    assert "No research has been committed" in state.message


def test_right_gameweek_but_old_is_ageing_not_stale():
    """Relative to now, not to a hardcoded date — a fixed timestamp silently
    becomes a future date and the check reads as fresh."""
    from datetime import datetime, timedelta, timezone

    long_ago = (datetime.now(timezone.utc) - timedelta(hours=60)).isoformat()
    state = freshness.check(gameweek=3, research_gameweek=3, researched_at=long_ago)
    assert state.state == freshness.AGEING
    assert not state.stale
    assert "worth a refresh" in state.message


def test_the_status_line_stays_short():
    from datetime import datetime, timezone
    state = freshness.check(gameweek=3, research_gameweek=3,
                            researched_at=datetime.now(timezone.utc).isoformat())
    assert state.label.startswith("Updated")
    assert len(state.label) < 40


def test_an_unparseable_timestamp_does_not_raise():
    state = freshness.check(gameweek=3, research_gameweek=3, researched_at="whenever")
    assert state.age_hours is None
    assert state.state == freshness.FRESH


def test_the_shipped_research_files_carry_the_stamps_the_check_needs():
    """Reads a real committed file rather than a fixture, because the bug
    this guards against is a research file that forgets to say which
    gameweek it is for — at which point the app cannot tell last week's
    reasoning from this week's.

    Note what is *not* asserted: that the file is FRESH. Freshness decays
    with the wall clock, so asserting it would turn a passing suite into a
    failing one every 36 hours with no code change. The gameweek-relative
    half is the part that is actually a property of the file.
    """
    import json

    payload = json.loads(
        (Path(__file__).resolve().parent.parent / "data" / "consensus" / "gw2.json").read_text()
    )
    assert payload.get("gameweek") == 2, "the file must say which deadline it is for"
    assert payload.get("researched"), "the file must say when it was written"

    assert not freshness.from_files(2, payload).stale, "right gameweek is never stale"
    assert freshness.from_files(3, payload).stale, "a gameweek behind is stale"


# --- the deployment contract --------------------------------------------

def test_nothing_in_requirements_costs_money():
    """The hard constraint. Every dependency must be free and installable
    on Streamlit Community Cloud's free tier."""
    text = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text().lower()
    for paid in ("anthropic", "openai", "boto3", "google-cloud", "snowflake",
                 "psycopg", "redis", "sentry", "datadog"):
        assert paid not in text, f"{paid} implies a paid service or account"


def test_the_app_makes_no_llm_api_calls():
    """Claude Code builds this app; the app must never call a metered API
    itself. A key in the deployed app would bill on every page load."""
    root = Path(__file__).resolve().parent.parent / "fpl_assistant"
    for source in root.rglob("*.py"):
        text = source.read_text().lower()
        assert "anthropic" not in text, f"{source.name} references anthropic"
        assert "openai" not in text, f"{source.name} references openai"
        assert "api_key" not in text, f"{source.name} references an api key"


def test_the_preflight_gate_exists_and_covers_the_deploy_risks():
    from scripts import preflight

    labels = [label for label, _ in preflight.CHECKS]
    assert "Python syntax" in labels
    assert "Critical imports" in labels
    assert "Requirements complete" in labels
    assert "App smoke test" in labels


# --- the automation must never go green having done nothing --------------

def test_the_squad_fetcher_fails_loudly_without_a_team_id(monkeypatch, capsys):
    """The bug this guards: `.env` is gitignored, so GitHub Actions had no
    team ID, and the fetch step printed a note and exited 0. Thirty-odd
    scheduled runs went green in a row while `data/squad/` was never once
    written, and nothing anywhere said so. A job that cannot do its work
    must fail, not succeed quietly."""
    from fpl_assistant import config
    from scripts import fetch_squad

    monkeypatch.setattr(fetch_squad, "FPL_TEAM_ID", None)
    monkeypatch.setattr(config, "FPL_TEAM_ID", None)

    assert fetch_squad.main() == 1, "a missing team ID must be a failure, not a no-op"
    out = capsys.readouterr().out
    assert "::error" in out, "GitHub Actions only surfaces ::error annotations"
    assert "FPL_TEAM_ID" in out, "the message must name the thing to configure"


def test_the_workflow_passes_the_team_id_to_both_scripts():
    """A repository variable only reaches a step that asks for it. The
    fetcher went unconfigured because the workflow never passed one."""
    text = (Path(__file__).resolve().parent.parent
            / ".github" / "workflows" / "snapshot.yml").read_text()
    assert text.count("FPL_TEAM_ID: ${{ vars.FPL_TEAM_ID }}") == 2, (
        "both the squad fetch and the snapshot step need the team ID"
    )
    assert "if: always()" in text, (
        "a missing team ID must not also stop the unrelated snapshot step"
    )

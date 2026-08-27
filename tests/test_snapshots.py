"""Tests for freezing the pre-deadline recommendation.

The rule the whole mechanism enforces is narrow and easy to get subtly
wrong: a snapshot may be rewritten as often as you like while the deadline
is ahead, and never once it has passed. The first version got this
backwards -- it refused to overwrite, which locked in whatever the app
happened to compute days early and threw away every later, better-informed
run. Late team news is exactly when the advice improves.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.analysis import optimiser, snapshots


@pytest.fixture(autouse=True)
def snapshot_dir(tmp_path, monkeypatch):
    directory = tmp_path / "snapshots"
    directory.mkdir()
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", directory)
    return directory


def _solution(captain=1, formation="4-4-2", points=60.0):
    ids = list(range(1, 16))
    return optimiser.SquadSolution(
        squad_ids=ids, starting_ids=ids[:11], bench_ids=ids[11:],
        captain_id=captain, vice_captain_id=2, formation=formation,
        total_cost=99.5, expected_points=points,
    )


# --- the rule -----------------------------------------------------------

def test_a_snapshot_round_trips():
    snapshots.save(1, _solution(), names={1: "Haaland", 2: "Salah"})
    loaded = snapshots.load(1)

    assert loaded is not None
    assert loaded.gameweek == 1
    assert loaded.captain_id == 1
    assert loaded.player_names["1"] == "Haaland"
    assert len(loaded.starting_ids) == 11


def test_a_later_pre_deadline_run_replaces_an_earlier_one():
    """Late team news is when the advice gets better, so a pre-deadline
    rewrite is not a corruption of the record — it is the record."""
    snapshots.save(1, _solution(captain=1, formation="4-4-2"))
    snapshots.save(1, _solution(captain=7, formation="3-5-2"))

    loaded = snapshots.load(1)
    assert loaded.captain_id == 7
    assert loaded.formation == "3-5-2"


def test_nothing_is_written_once_the_deadline_has_passed():
    """The point of the module. A post-kick-off save would replace real
    advice with something informed by results already in."""
    snapshots.save(1, _solution(captain=1))
    snapshots.save(1, _solution(captain=99), deadline_passed=True)

    assert snapshots.load(1).captain_id == 1


def test_a_post_deadline_save_does_not_create_a_missing_snapshot():
    assert snapshots.save(1, _solution(), deadline_passed=True) is None
    assert snapshots.load(1) is None


def test_a_missing_snapshot_reads_as_missing():
    assert snapshots.load(42) is None


def test_a_corrupt_snapshot_reads_as_missing_rather_than_raising(snapshot_dir):
    (snapshot_dir / "gw3.json").write_text("{not json")
    assert snapshots.load(3) is None


def test_an_unwritable_directory_does_not_raise(monkeypatch):
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", Path("/proc/nonexistent/snapshots"))
    assert snapshots.save(1, _solution()) is None


# --- the scheduled writer ----------------------------------------------

def _bootstrap(hours_to_deadline: float):
    import tests.test_app_smoke as smoke

    data = smoke._synthetic_bootstrap(preseason=True)
    now = datetime.now(timezone.utc)
    for offset, event in enumerate(data["events"]):
        event["deadline_time"] = (
            now + timedelta(hours=hours_to_deadline) + timedelta(days=7 * offset)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        event["finished"] = False
    return data


def _run_script(monkeypatch, hours_to_deadline: float) -> int:
    import tests.test_app_smoke as smoke
    from fpl_assistant import api

    import scripts.snapshot_gameweek as script

    monkeypatch.setattr(api, "get_bootstrap_static", lambda: _bootstrap(hours_to_deadline))
    monkeypatch.setattr(api, "get_fixtures", lambda event=None: smoke._synthetic_fixtures())
    return script.main()


def test_the_scheduled_writer_snapshots_close_to_the_deadline(monkeypatch):
    assert _run_script(monkeypatch, hours_to_deadline=6) == 0
    saved = snapshots.load(1)
    assert saved is not None
    assert len(saved.squad_ids) == 15
    assert saved.player_names, "player names should be recorded so the frozen view reads"


def test_the_scheduled_writer_stays_quiet_when_the_deadline_is_far_off(monkeypatch):
    """A snapshot taken days out is a guess. Most scheduled runs should do
    nothing, and doing nothing is not a failure."""
    assert _run_script(monkeypatch, hours_to_deadline=200) == 0
    assert snapshots.load(1) is None


def test_the_scheduled_writer_refuses_after_the_deadline(monkeypatch):
    assert _run_script(monkeypatch, hours_to_deadline=-3) == 0
    assert snapshots.load(1) is None


def test_the_repo_holds_no_snapshot_built_from_test_data():
    """Regression: running the app smoke tests wrote a snapshot into the
    real directory, and it got committed. The app would then have shown a
    squad of synthetic fixture players as its genuine pre-deadline
    recommendation — a fabricated record, which is worse than none.
    """
    import json

    real_dir = Path(__file__).resolve().parent.parent / "data" / "snapshots"
    for path in real_dir.glob("gw*.json"):
        data = json.loads(path.read_text())
        names = " ".join(data.get("player_names", {}).values())
        assert "Adeyemi" not in names and "Okafor" not in names, (
            f"{path.name} contains synthetic test players"
        )


# --- the projections, kept alongside the decision ------------------------

def test_a_snapshot_records_what_each_player_was_projected_to_score():
    """Without this the snapshot is a record, not an audit.

    Knowing the app picked a player tells you nothing about whether the
    model was right — you need the number it committed to beforehand, or
    there is no way to check the projections against what happened.
    """
    snapshots.save(
        3, _solution(), names={1: "Haaland"}, projected={1: 7.4, 2: 5.128},
    )
    loaded = snapshots.load(3)

    assert loaded.projected["1"] == 7.4
    assert loaded.projected["2"] == 5.13  # rounded, not truncated


def test_an_old_snapshot_without_projections_still_loads():
    """Snapshots written before projections were recorded must not break
    the app — a missing field means 'unknown', not 'corrupt file'."""
    import json

    snapshots.save(4, _solution())
    path = snapshot_dir_path = snapshots.SNAPSHOT_DIR / "gw4.json"
    data = json.loads(path.read_text())
    del data["projected"]
    path.write_text(json.dumps(data))

    loaded = snapshots.load(4)
    assert loaded is not None
    assert loaded.projected == {}

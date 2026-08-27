"""Tests for marking the app's own homework.

The point of this module is that it can embarrass the rest of the app, so
the tests are written to make sure it actually can: a captain that blanked
must be reported as a captain that blanked, and a projection that was two
points high must show up as two points high. A scorer that quietly rounds
its own failures off is worse than no scorer at all.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant.analysis import accuracy, snapshots


def _snapshot(projected=None, captain_id=1, starting=None):
    squad = list(range(1, 16))
    starting = starting or squad[:11]
    return snapshots.Snapshot(
        gameweek=1,
        saved_at="2025-08-15T10:00:00+00:00",
        squad_ids=squad,
        starting_ids=starting,
        bench_ids=[i for i in squad if i not in starting],
        captain_id=captain_id,
        vice_captain_id=2,
        formation="4-4-2",
        total_cost=99.5,
        expected_points=62.0,
        player_names={str(i): f"Player {i}" for i in squad},
        projected={str(k): v for k, v in (projected or {}).items()},
    )


def _live(points_by_id, minutes=90):
    return {
        "elements": [
            {"id": pid, "stats": {"total_points": pts, "minutes": minutes}}
            for pid, pts in points_by_id.items()
        ]
    }


def _positions():
    # 2 keepers, 5 defenders, 5 midfielders, 3 forwards -- a legal squad.
    order = ["GKP"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    return {i + 1: pos for i, pos in enumerate(order)}


# --- the basic arithmetic ----------------------------------------------

def test_the_captain_is_counted_twice():
    actuals = accuracy.actuals_from_live(_live({i: 2 for i in range(1, 16)}))
    score = accuracy.score_gameweek(_snapshot(captain_id=1), actuals)

    # Eleven starters on 2 each, plus the captain's 2 again.
    assert score.xi_points == 24


def test_bench_points_are_reported_separately():
    points = {i: 1 for i in range(1, 16)}
    points.update({12: 9, 13: 9, 14: 9, 15: 9})
    actuals = accuracy.actuals_from_live(_live(points))
    score = accuracy.score_gameweek(_snapshot(), actuals)

    assert score.bench_points == 36
    assert score.xi_points == 12


def test_a_player_missing_from_the_live_data_scores_zero():
    # Only ten of the eleven starters appear. The eleventh did not score.
    actuals = accuracy.actuals_from_live(_live({i: 5 for i in range(1, 11)}))
    score = accuracy.score_gameweek(_snapshot(captain_id=1), actuals)

    assert score.xi_points == 55  # 10 x 5, plus the captain again
    assert any(p.player_id == 11 and p.actual == 0 for p in score.players)


# --- was the decision good? --------------------------------------------

def test_a_blanking_captain_is_reported_as_a_cost():
    points = {i: 2 for i in range(1, 16)}
    points[1] = 1   # the captain
    points[5] = 14  # the one who should have had it
    actuals = accuracy.actuals_from_live(_live(points))
    score = accuracy.score_gameweek(_snapshot(captain_id=1), actuals)

    assert not score.captain_was_best
    assert score.best_captain_id == 5
    assert score.captain_cost == 13
    assert "captaincy cost 13 points" in score.verdict


def test_the_right_captain_is_credited():
    points = {i: 2 for i in range(1, 16)}
    points[1] = 15
    actuals = accuracy.actuals_from_live(_live(points))
    score = accuracy.score_gameweek(_snapshot(captain_id=1), actuals)

    assert score.captain_was_best
    assert score.captain_cost == 0
    assert "right player" in score.verdict


def test_a_bench_haul_shows_up_as_selection_cost():
    points = {i: 2 for i in range(1, 16)}
    points[14] = 16  # a benched midfielder hauled
    actuals = accuracy.actuals_from_live(_live(points))
    score = accuracy.score_gameweek(_snapshot(), actuals, positions=_positions())

    assert score.bench_cost > 0
    assert "sat on the bench" in score.verdict


def test_a_correctly_picked_eleven_leaves_nothing_on_the_bench():
    # Starters all outscore the bench, so hindsight picks the same XI.
    points = {i: (8 if i <= 11 else 1) for i in range(1, 16)}
    actuals = accuracy.actuals_from_live(_live(points))
    score = accuracy.score_gameweek(_snapshot(), actuals, positions=_positions())

    assert score.bench_cost == 0


def test_it_is_compared_against_the_average_manager():
    actuals = accuracy.actuals_from_live(_live({i: 5 for i in range(1, 16)}))
    score = accuracy.score_gameweek(_snapshot(), actuals, average_entry_score=50.0)

    assert score.vs_average == 10.0
    assert "above the average manager" in score.verdict


# --- was the projection good? ------------------------------------------

def test_a_model_that_projects_too_high_is_reported_as_too_high():
    projected = {i: 6.0 for i in range(1, 16)}
    actuals = accuracy.actuals_from_live(_live({i: 4 for i in range(1, 16)}))
    score = accuracy.score_gameweek(_snapshot(projected=projected), actuals)
    report = accuracy.calibrate([score])

    assert report.bias == -2.0
    assert report.mean_absolute_error == 2.0
    assert "2.00 points high" in report.verdict


def test_a_well_calibrated_model_is_told_so():
    projected = {i: 4.2 for i in range(1, 16)}
    actuals = accuracy.actuals_from_live(_live({i: 4 for i in range(1, 16)}))
    report = accuracy.calibrate(
        [accuracy.score_gameweek(_snapshot(projected=projected), actuals)]
    )

    assert "well calibrated" in report.verdict


def test_offsetting_position_errors_do_not_cancel_into_a_clean_bill_of_health():
    """The failure this exists to catch.

    Defenders projected four points too high and forwards four too low
    average out to a bias of zero -- a model that looks perfect and is
    wrong about every single player. Only the per-position split shows it.
    """
    positions = _positions()
    projected = {}
    points = {}
    for pid, position in positions.items():
        if position == "DEF":
            projected[pid], points[pid] = 7.6, 4   # five of them, -3.6 each
        elif position == "FWD":
            projected[pid], points[pid] = 2.0, 8   # three of them, +6.0 each
        else:
            projected[pid], points[pid] = 4.0, 4

    actuals = accuracy.actuals_from_live(_live(points))
    score = accuracy.score_gameweek(
        _snapshot(projected=projected), actuals, positions=positions
    )
    report = accuracy.calibrate([score])

    assert abs(report.bias) < 0.5
    assert "well calibrated" in report.verdict  # the aggregate is fooled
    notes = " ".join(report.position_notes)
    assert "DEF: overrated" in notes
    assert "FWD: underrated" in notes


def test_players_who_did_not_feature_are_excluded_from_calibration():
    """A projection for someone who was dropped is a team-news miss.

    Counting it as a scoring-model miss makes the model look wildly
    pessimistic and hides the actual problem, so those players are left
    out of the calibration entirely.
    """
    projected = {i: 5.0 for i in range(1, 16)}
    live = {
        "elements": [
            {"id": i, "stats": {"total_points": 5, "minutes": 90 if i <= 11 else 0}}
            for i in range(1, 16)
        ]
    }
    actuals = accuracy.actuals_from_live(live)
    report = accuracy.calibrate(
        [accuracy.score_gameweek(_snapshot(projected=projected), actuals)]
    )

    assert report.sample == 11
    assert report.bias == 0.0


def test_the_worst_misses_are_named():
    projected = {i: 3.0 for i in range(1, 16)}
    projected[7] = 11.0  # badly overrated
    points = {i: 3 for i in range(1, 16)}
    points[9] = 15       # badly underrated
    actuals = accuracy.actuals_from_live(_live(points))
    report = accuracy.calibrate(
        [accuracy.score_gameweek(_snapshot(projected=projected), actuals)]
    )

    assert [p.player_id for p in report.worst_overrated] == [7]
    assert [p.player_id for p in report.worst_underrated] == [9]


def test_nothing_to_score_is_said_plainly():
    report = accuracy.calibrate([])
    assert report.sample == 0
    assert "nothing to score" in report.verdict.lower()


# --- the history walk ---------------------------------------------------

@pytest.fixture
def snapshot_dir(tmp_path, monkeypatch):
    directory = tmp_path / "snapshots"
    directory.mkdir()
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", directory)
    return directory


def test_history_skips_gameweeks_with_no_snapshot(snapshot_dir):
    import json
    from dataclasses import asdict

    (snapshot_dir / "gw1.json").write_text(json.dumps(asdict(_snapshot())))
    scores = accuracy.score_history(
        [1, 2, 3], lambda gw: _live({i: 4 for i in range(1, 16)})
    )

    assert [s.gameweek for s in scores] == [1]


def test_one_broken_fetch_does_not_kill_the_report(snapshot_dir):
    import json
    from dataclasses import asdict

    for gw in (1, 2):
        snap = _snapshot()
        snap.gameweek = gw
        (snapshot_dir / f"gw{gw}.json").write_text(json.dumps(asdict(snap)))

    def fetch(gameweek):
        if gameweek == 1:
            raise RuntimeError("endpoint down")
        return _live({i: 4 for i in range(1, 16)})

    scores = accuracy.score_history([1, 2], fetch)
    assert [s.gameweek for s in scores] == [2]

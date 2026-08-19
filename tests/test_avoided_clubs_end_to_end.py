"""The regression test for the bug the user actually reported.

Symptom: "Experts are saying avoid Bournemouth and you're still picking
Bournemouth defenders?"

The unit tests in test_club_stances.py check that a club verdict produces
a penalty. That is necessary and not sufficient -- the penalty could be
computed correctly and then be too small to change any decision, which
from the outside is identical to not having it. The only test that
actually answers the user's complaint runs the whole pipeline and looks at
who ends up in the fifteen.

So this builds a pool where the flagged club's defenders are *deliberately
attractive* -- cheap, and no worse on paper than anyone else, which is
precisely why the optimiser kept buying them -- and asserts they are not
selected.
"""
import json

import pandas as pd
import pytest

from fpl_assistant.analysis import consensus
from fpl_assistant.analysis.squad_builder import recommend_squad, score_players

N_TEAMS = 20
FLAGGED = "T3"  # stands in for Bournemouth


@pytest.fixture
def stance_dir(tmp_path, monkeypatch):
    """Points the consensus loader at a directory we control, and hands
    back a switch for writing the flagged club's verdict or not."""
    directory = tmp_path / "consensus"
    directory.mkdir(exist_ok=True)
    monkeypatch.setattr(consensus, "CONSENSUS_DIR", directory)

    def _write(with_stance: bool):
        teams = [{
            "short_name": FLAGGED,
            "stances": [{"stance": "avoid", "scope": "all", "until_gameweek": 9,
                         "case": "Worst opening run in the league; avoid until it clears."}],
        }] if with_stance else []
        (directory / "teams.json").write_text(json.dumps({"teams": teams}))

    return _write


def _players() -> pd.DataFrame:
    """A pool where the flagged club's players look like modestly better
    value than everyone else, so without the expert verdict they get
    picked.

    That construction is the point. In real FPL a club with a brutal run
    has cheap assets precisely because of the run, and a model reading
    price and per-90 rates sees a bargain while missing the reason for the
    bargain. A test where the flagged players were unremarkable would pass
    with the feature deleted.

    The size of the edge is deliberately modest. A club verdict is a
    weighted opinion, not a veto -- a genuinely elite player is still
    worth owning through a bad run, and a test built on players who were
    twice as good as the field would be asserting the wrong thing, namely
    that expert opinion should override any amount of evidence.
    """
    rows = []
    pid = 1
    counts = {"GKP": 3, "DEF": 8, "MID": 8, "FWD": 5}
    for team in range(1, N_TEAMS + 1):
        flagged = f"T{team}" == FLAGGED
        for pos, n in counts.items():
            for i in range(n):
                price = round(4.0 + i * 0.7, 1)
                # Deterministic per-player jitter. Without it every club is
                # a perfect copy of every other, and a perfectly symmetric
                # integer program is pathological for branch-and-bound --
                # the solver wanders through thousands of equivalent optima.
                # Real player pools are never that uniform.
                points = 40 + i * 8 + (pid % 7)
                rows.append({
                    "id": pid, "web_name": f"{pos}{pid}", "team": team,
                    "team_short_name": f"T{team}", "position": pos,
                    "now_cost": int(price * 10), "price": price,
                    # Same price, materially more points: unbeatable value.
                    "total_points": int(points * (1.2 if flagged else 1)),
                    "points_per_game": (points * (1.2 if flagged else 1)) / 20,
                    "form": 5.0, "minutes": 1800, "starts": 20,
                    "selected_by_percent": 5.0, "status": "a",
                    "status_label": "Available", "news": "",
                    "chance_of_playing_next_round": 100,
                    "expected_goals_per_90": 0.3 * (1.2 if flagged else 1),
                    "expected_assists_per_90": 0.2 * (1.2 if flagged else 1),
                    "expected_goal_involvements": 5.0,
                    "expected_goals_conceded_per_90": 1.2,
                    "expected_goals_conceded": 24.0,
                    "saves_per_90": 0.0, "saves": 0, "bonus": 6,
                    "defensive_contribution": 4, "yellow_cards": 1, "red_cards": 0,
                })
                pid += 1
    return pd.DataFrame(rows).set_index("id", drop=False)


def _teams() -> pd.DataFrame:
    return pd.DataFrame(
        [{"id": t, "name": f"Team{t}", "short_name": f"T{t}"} for t in range(1, N_TEAMS + 1)]
    ).set_index("id", drop=False)


def _fixtures(from_event: int = 1, n: int = 5) -> pd.DataFrame:
    rows = []
    for gw in range(from_event, from_event + n):
        for i in range(0, N_TEAMS, 2):
            rows.append({"event": gw, "team_h": i + 1, "team_a": i + 2,
                         "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": False})
    return pd.DataFrame(rows)


def _squad(from_event: int) -> tuple[list[str], list[int]]:
    scored = score_players(_players(), _fixtures(from_event), _teams(), from_event=from_event)
    solution = recommend_squad(scored)
    picked = scored[scored["id"].isin(solution.squad_ids)]
    return picked["team_short_name"].tolist(), sorted(solution.squad_ids)


def test_no_players_are_picked_from_a_club_the_experts_say_to_avoid(stance_dir):
    """The user's actual complaint, as an assertion."""
    stance_dir(with_stance=True)
    clubs, _ = _squad(from_event=1)
    assert FLAGGED not in clubs


def test_the_verdict_is_what_changes_the_squad(stance_dir):
    """Guards against a test that passes for the wrong reason.

    Every club in this pool is identical, so if the flagged club happened
    not to be selected anyway, the test above would pass with the feature
    deleted. Running the same pool without the verdict has to produce a
    different fifteen.
    """
    stance_dir(with_stance=False)
    without, without_ids = _squad(from_event=1)
    stance_dir(with_stance=True)
    _, with_ids = _squad(from_event=1)

    assert FLAGGED in without, "the flagged club is picked when nobody warns against it"
    assert with_ids != without_ids


def test_an_expired_verdict_changes_nothing_at_all(stance_dir):
    """The other half of the requirement, and the easy thing to get wrong.

    The advice was "avoid until GW9", not "avoid forever". Asserting the
    club gets picked again would be a coin flip here -- twenty identical
    clubs, and the solver breaks ties arbitrarily. The real requirement is
    stronger and testable: past its expiry the verdict must have no effect
    whatsoever, so the squad must match one solved with no verdict at all.
    """
    stance_dir(with_stance=True)
    _, expired_ids = _squad(from_event=9)
    stance_dir(with_stance=False)
    _, clean_ids = _squad(from_event=9)

    assert expired_ids == clean_ids


def test_the_penalty_is_visible_on_the_players_themselves(stance_dir):
    stance_dir(with_stance=True)
    scored = score_players(_players(), _fixtures(1), _teams(), from_event=1)
    flagged = scored[scored["team_short_name"] == FLAGGED]

    assert (flagged["club_stance"] == "avoid").all()
    # And it must actually move the number the optimiser reads, not just
    # sit in a display column.
    assert (flagged["xp_horizon"] < flagged["xp_pre_consensus"]).all()

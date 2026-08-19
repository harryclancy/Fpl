

def test_unscheduled_gameweeks_are_not_counted_as_blanks():
    """A gameweek no team has a fixture in hasn't been scheduled yet.
    Counting it as a blank gave every club in the league an identical
    phantom blank, which is both wrong and useless."""
    import pandas as pd
    from fpl_assistant.analysis.fixtures import team_fixture_table

    teams = pd.DataFrame(
        [{"id": t, "name": f"Team{t}", "short_name": f"T{t}"} for t in range(1, 5)]
    ).set_index("id", drop=False)
    # Fixtures only exist for GW1-2; the window asks for four.
    fixtures = pd.DataFrame([
        {"event": gw, "team_h": h, "team_a": a, "team_h_difficulty": 3,
         "team_a_difficulty": 3, "finished": False}
        for gw in (1, 2) for h, a in [(1, 2), (3, 4)]
    ])

    table = team_fixture_table(fixtures, teams, from_event=1, n_gameweeks=4)
    assert (table["blank_gameweeks"] == 0).all()

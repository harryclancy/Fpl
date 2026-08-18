"""Tests for report-to-player cross-referencing in rationale.py.

FPL's compact `web_name` (often just a surname, sometimes styled
"B.Fernandes") frequently won't literally match how a report written in
prose refers to a player ("Bruno Fernandes"). This locks in that the
match falls back to first+second name too.
"""
import pandas as pd

from fpl_assistant.analysis.rationale import _report_mention, captain_rationale, player_rationale

REPORT_TEXT = """
## Player notes

- **Bruno Fernandes** (Man Utd) — best fixture swing of any side, back-to-back promoted sides.
- **Havertz** — the headline GW1 differential pick, sub-7% ownership.
"""


def _row(**overrides):
    base = {
        "id": 1, "code": 100, "web_name": "B.Fernandes", "first_name": "Bruno",
        "second_name": "Fernandes", "team": 1, "team_short_name": "MUN", "position": "MID",
        "price": 9.0, "selected_by_percent": 20.0, "scoring_basis": "preseason",
        "fixture_run_difficulty": 2.5, "chance_of_playing_next_round": 100, "news": "",
        "transfers_in_event": 0, "transfers_out_event": 0,
    }
    base.update(overrides)
    return pd.Series(base)


def test_report_mention_matches_full_name_not_just_web_name():
    row = _row()
    mention = _report_mention(row, REPORT_TEXT)
    assert mention is not None
    assert "fixture swing" in mention


def test_report_mention_falls_back_to_surname_only():
    row = _row(web_name="Havertz", first_name="Kai", second_name="Havertz")
    mention = _report_mention(row, REPORT_TEXT)
    assert mention is not None
    assert "differential" in mention


def test_report_mention_none_when_no_match():
    row = _row(web_name="Nobody", first_name="No", second_name="Body")
    assert _report_mention(row, REPORT_TEXT) is None


def test_player_rationale_surfaces_mention_prominently():
    row = _row()
    text = player_rationale(row, REPORT_TEXT)
    assert "What FPL managers & analysts are saying" in text
    assert "fixture swing" in text


def test_captain_rationale_checks_both_captain_and_vice():
    captain = _row()
    vice = _row(id=2, web_name="Havertz", first_name="Kai", second_name="Havertz", code=101)
    text = captain_rationale(captain, vice, REPORT_TEXT)
    assert "fixture swing" in text
    assert "differential" in text

"""Turns a scored player row into a plain-English writeup explaining the pick.

Template-based, not an LLM call — this needs to run standalone inside the
deployed Streamlit app with no external API access. References whichever
signals actually went into `squad_score` (see squad_builder.score_players):
price/ownership/fixture preseason, form/xGI/xGC once matches are being
played — plus extra depth (ICT index, transfer momentum, injury/rotation
risk, and a cross-reference to this week's Odds & Expert Take report when
one is available) so each pick reads as a real case, not just one number.
"""
import re

import pandas as pd

FIXTURE_WINDOW = 5
TRANSFER_MOMENTUM_THRESHOLD = 20_000


def _difficulty_label(avg_fdr: float) -> str:
    if avg_fdr <= 2.4:
        return "excellent"
    if avg_fdr <= 3.0:
        return "good"
    if avg_fdr <= 3.5:
        return "average"
    if avg_fdr <= 4.0:
        return "tough"
    return "very tough"


def _form_label(form: float) -> str:
    if form >= 7:
        return "excellent"
    if form >= 5:
        return "strong"
    if form >= 3:
        return "decent"
    return "modest"


def _momentum_note(row: pd.Series) -> str | None:
    net = row.get("transfers_in_event", 0) - row.get("transfers_out_event", 0)
    if net >= TRANSFER_MOMENTUM_THRESHOLD:
        return f"gaining **{net:,.0f}** net transfers in this week — the crowd is moving toward them."
    if net <= -TRANSFER_MOMENTUM_THRESHOLD:
        return f"bleeding **{abs(net):,.0f}** net transfers out this week — worth knowing why before you follow."
    return None


def _risk_note(row: pd.Series) -> str | None:
    chance = row.get("chance_of_playing_next_round", 100)
    news = str(row.get("news", "") or "").strip()
    if chance is not None and chance < 100:
        detail = f" — {news}" if news else ""
        return f"⚠️ Only **{chance:.0f}%** chance of playing next round{detail}."
    if news:
        return f"⚠️ {news}"
    return None


def _report_mention(row: pd.Series, report_text: str | None) -> str | None:
    """If this week's Odds & Expert Take report mentions this player by
    name, surface the line it appears in as corroborating (or
    contradicting) evidence.
    """
    if not report_text:
        return None
    name = str(row["web_name"])
    for line in report_text.splitlines():
        if re.search(rf"\b{re.escape(name)}\b", line, re.IGNORECASE):
            snippet = line.strip().lstrip("-*# ").strip()
            if snippet:
                return f'📰 This week\'s report backs it up: "{snippet}"'
    return None


def _key_stats_line(row: pd.Series, preseason: bool) -> str:
    parts = [f"£{row['price']:.1f}m", f"{row['selected_by_percent']:.1f}% owned"]
    if not preseason:
        ict = row.get("ict_index")
        bonus = row.get("bonus")
        if ict is not None:
            parts.append(f"ICT {ict:.1f}")
        if bonus:
            parts.append(f"{bonus:.0f} bonus pts banked")
    return "Key stats: " + " · ".join(parts)


def player_rationale(row: pd.Series, report_text: str | None = None) -> str:
    name = row["web_name"]
    team = row["team_short_name"]
    price = row["price"]
    difficulty = row["fixture_run_difficulty"]
    difficulty_label = _difficulty_label(difficulty)
    preseason = row.get("scoring_basis") == "preseason"

    if preseason:
        ownership = row["selected_by_percent"]
        body = (
            f"**{name}** ({team}, £{price:.1f}m) — no in-season form to go on yet, so this is a "
            f"preseason call built on price, ownership, and fixtures. At £{price:.1f}m the market/FPL's "
            f"own pricing already reflects expected quality, and {ownership:.1f}% ownership shows the "
            f"community rates them too. Their run over the next {FIXTURE_WINDOW} gameweeks grades as "
            f"**{difficulty_label}** ({difficulty:.1f} avg FDR), which is the deciding factor tipping "
            f"them into this XI."
        )
    else:
        form = row["form"]
        xgi = row["expected_goal_involvements"]
        xgc = row.get("expected_goals_conceded", 0)
        form_label = _form_label(form)

        if row["position"] in ("MID", "FWD"):
            body = (
                f"**{name}** ({team}, £{price:.1f}m) is in **{form_label} form** ({form:.1f} recent form) "
                f"and has racked up {xgi:.1f} expected goal involvements — that's genuine underlying "
                f"output, not just a points spike. Their fixture run over the next {FIXTURE_WINDOW} "
                f"gameweeks grades as **{difficulty_label}** ({difficulty:.1f} avg FDR), which supports "
                f"starting them now."
            )
        else:
            body = (
                f"**{name}** ({team}, £{price:.1f}m) is in **{form_label} form** ({form:.1f} recent form) "
                f"with {xgc:.2f} expected goals conceded, a solid defensive underlying number. Their run "
                f"over the next {FIXTURE_WINDOW} gameweeks grades as **{difficulty_label}** "
                f"({difficulty:.1f} avg FDR) — good conditions for clean-sheet points."
            )

    extra_lines = [_risk_note(row), _momentum_note(row), _report_mention(row, report_text)]
    extra_lines = [line for line in extra_lines if line]
    extra_lines.append(_key_stats_line(row, preseason))

    return body + "\n\n" + "  \n".join(extra_lines)


def captain_rationale(captain_row: pd.Series, vice_row: pd.Series, report_text: str | None = None) -> str:
    c_name, v_name = captain_row["web_name"], vice_row["web_name"]
    if captain_row.get("scoring_basis") == "preseason":
        body = (
            f"**Captain: {c_name}.** Highest combined price/ownership/fixture score among your "
            f"attacking starters — the market and the crowd both rate them, and the fixture backs it "
            f"up. **{v_name}** is the safety-net vice if {c_name} doesn't start or gets injured "
            f"pre-deadline."
        )
    else:
        body = (
            f"**Captain: {c_name}.** Best blend of current form, underlying attacking numbers, and "
            f"fixture difficulty among your starters — the standard armband logic: double points on the "
            f"player most likely to deliver a big score. **{v_name}** is the vice, ready to inherit the "
            f"armband if {c_name} doesn't play."
        )

    mention = _report_mention(captain_row, report_text)
    return body + ("\n\n" + mention if mention else "")

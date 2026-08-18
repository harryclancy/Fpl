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


def _name_candidates(row: pd.Series) -> list[str]:
    """Every reasonable way this player might be referred to in prose.

    FPL's compact `web_name` (often just a surname, sometimes styled
    "B.Fernandes") frequently won't literally appear in a research report
    written the way a human would — "Bruno Fernandes", not "B.Fernandes".
    Try the surname and the full first+second name too, longest first so
    a full-name match wins over a generic surname match when both hit.
    """
    candidates = {str(row["web_name"])}
    second_name = row.get("second_name")
    first_name = row.get("first_name")
    if pd.notna(second_name) and second_name:
        candidates.add(str(second_name))
    if pd.notna(first_name) and pd.notna(second_name) and first_name and second_name:
        candidates.add(f"{first_name} {second_name}")
    return sorted((c for c in candidates if c), key=len, reverse=True)


def _report_mention(row: pd.Series, report_text: str | None) -> str | None:
    """If this week's Odds & Expert Take report mentions this player under
    any of their name variants, surface the line/bullet it appears in as
    corroborating (or contradicting) community/analyst evidence.
    """
    if not report_text:
        return None
    for name in _name_candidates(row):
        for line in report_text.splitlines():
            if re.search(rf"\b{re.escape(name)}\b", line, re.IGNORECASE):
                snippet = line.strip().lstrip("-*# ").strip()
                if snippet:
                    return snippet
    return None


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
            f"**{name}** ({team}, £{price:.1f}m) — no in-season form to judge yet, so this leans on what "
            f"the price and the crowd already know. FPL's pricing algorithm and the transfer market both "
            f"price in *expected* role and quality before a ball's kicked, so £{price:.1f}m is itself a "
            f"signal, not just a cost — and {ownership:.1f}% ownership means a lot of other managers did "
            f"the same homework and landed here too. On top of that, their opponents over the next "
            f"{FIXTURE_WINDOW} gameweeks grade as **{difficulty_label}** ({difficulty:.1f} avg FDR) — "
            f"weaker opposition defences/attacks specifically, which is the tie-breaker that tipped them "
            f"into this XI over a similarly-priced alternative."
        )
    else:
        form = row["form"]
        xgi = row["expected_goal_involvements"]
        xgc = row.get("expected_goals_conceded", 0)
        form_label = _form_label(form)

        if row["position"] in ("MID", "FWD"):
            body = (
                f"**{name}** ({team}, £{price:.1f}m) is in **{form_label} form** ({form:.1f} recent form). "
                f"The reason that's trustworthy rather than a hot streak: {xgi:.1f} expected goal "
                f"involvements means they're consistently getting into good scoring/passing positions, "
                f"not just riding a few lucky finishes — underlying output like that tends to repeat. "
                f"Add in a **{difficulty_label}** run of opponents over the next {FIXTURE_WINDOW} "
                f"gameweeks ({difficulty:.1f} avg FDR — weaker defences ahead), and both the process and "
                f"the matchups point the same way."
            )
        else:
            body = (
                f"**{name}** ({team}, £{price:.1f}m) is in **{form_label} form** ({form:.1f} recent form), "
                f"backed by {xgc:.2f} expected goals conceded — a low number here means their side isn't "
                f"just riding shutout luck, they're structurally not allowing much, which is the kind of "
                f"defensive process clean sheets actually come from. Their next {FIXTURE_WINDOW} "
                f"gameweeks grade as **{difficulty_label}** ({difficulty:.1f} avg FDR) against attacks "
                f"that aren't going to test that much."
            )

    parts = [body]

    mention = _report_mention(row, report_text)
    if mention:
        parts.append(f'**What FPL managers & analysts are saying:** {mention}')
    else:
        parts.append(
            f"*No specific community/analyst commentary on {name} in this week's research — the case "
            f"above is numbers only. Ask about them in the question box below and I'll dig deeper.*"
        )

    extra_lines = [_risk_note(row), _momentum_note(row)]
    extra_lines = [line for line in extra_lines if line]
    if extra_lines:
        parts.append("  \n".join(extra_lines))
    parts.append("*Full fixture list, form, and underlying stats in the dropdown below.*")

    return "\n\n".join(parts)


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

    parts = [body]
    captain_mention = _report_mention(captain_row, report_text)
    if captain_mention:
        parts.append(f'**What FPL managers & analysts are saying about {c_name}:** {captain_mention}')
    vice_mention = _report_mention(vice_row, report_text)
    if vice_mention:
        parts.append(f'**On the vice, {v_name}:** {vice_mention}')
    return "\n\n".join(parts)

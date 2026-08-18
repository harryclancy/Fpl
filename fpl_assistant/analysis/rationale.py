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


def _fixture_clause(avg_fdr: float, attacking: bool) -> str:
    """Describes what the upcoming run means, honestly in both directions.

    These sentences used to assert "weaker defences ahead" unconditionally,
    which produced flat self-contradictions whenever the run was hard --
    a player could be described as facing a "very tough" run of "weaker
    defences" in the same clause. A tough run is a real argument against a
    pick and the writeup has to be able to say so.
    """
    if avg_fdr <= 3.0:
        return (
            "weaker opposition defences ahead — more space and more shots"
            if attacking
            else "attacks that shouldn't test them much, so clean sheets are live"
        )
    if avg_fdr <= 3.5:
        return (
            "a mixed run — a couple of favourable matchups among tougher ones"
            if attacking
            else "a mixed run of attacks: some clean-sheet chances, some not"
        )
    return (
        "a genuinely hard run, and the clearest argument *against* them; they're in this side on "
        "underlying quality, not on the schedule"
        if attacking
        else "attacks that will test them, so the clean-sheet case is weaker than the rest"
    )


def _form_label(form: float) -> str:
    if form >= 7:
        return "excellent"
    if form >= 5:
        return "strong"
    if form >= 3:
        return "decent"
    return "modest"


CONSENSUS_HEADLINES = {
    "must_have": "✅ **Consensus must-have.**",
    "strong": "👍 **Widely backed by analysts.**",
    "value": "💡 **A popular value pick.**",
    "avoid": "🚫 **Analysts are steering clear.**",
}


def consensus_verdict(row: pd.Series) -> str | None:
    """What the experts and the wider community actually said about this
    player, and what the app did with it.

    Stated plainly, including the consequence, because a verdict the
    selection engine acts on should be visible to the person reading the
    recommendation -- otherwise the squad looks arbitrary.
    """
    tier = row.get("consensus_tier")
    if not tier or pd.isna(tier):
        return None

    headline = CONSENSUS_HEADLINES.get(tier)
    if not headline:
        return None

    reason = row.get("consensus_reason")
    text = f"{headline} {reason}" if reason and pd.notna(reason) else headline

    if tier == "must_have":
        text += (
            " **This one is locked into the squad**, rather than left to the projection to argue "
            "for — at this level of agreement, fading him is an active bet against the field."
        )
    return text


def set_piece_note(row: pd.Series) -> str | None:
    """Dead-ball duties, spelled out as the causal reason they are.

    This is the single biggest swing in a player's ceiling that isn't
    visible in their price or their form line: a penalty taker converts
    roughly four-fifths of the spot-kicks his side wins, so the job is
    worth most of an extra goal every handful of games on its own -- and
    it transfers the moment a manager reassigns it, which is exactly the
    kind of change a form-based model notices far too late.
    """
    notes = []
    penalties = row.get("penalties_order")
    corners = row.get("corners_and_indirect_freekicks_order")
    freekicks = row.get("direct_freekicks_order")

    if pd.notna(penalties) and penalties == 1:
        notes.append(
            "**on penalties** — first-choice taker, which is worth close to an extra goal every "
            "few games before they've done anything in open play"
        )
    elif pd.notna(penalties) and penalties == 2:
        notes.append("second in line for penalties (inherits the job if the taker is off the pitch)")

    if pd.notna(freekicks) and freekicks == 1:
        notes.append("takes **direct free-kicks**")
    if pd.notna(corners) and corners == 1:
        notes.append("**on corners** — repeatable assist source rather than a one-off")

    if not notes:
        return None
    return f"🎯 Set-piece duty: {', '.join(notes)}."


def _minutes_note(row: pd.Series) -> str | None:
    """Starting certainty, framed as the risk it actually is."""
    expected_minutes = row.get("expected_minutes")
    p_start = row.get("p_start")
    if expected_minutes is None or pd.isna(expected_minutes):
        return None

    if p_start is not None and pd.notna(p_start):
        if p_start >= 0.85:
            return (
                f"⏱️ **Nailed on** — starts about {p_start * 100:.0f}% of the time "
                f"({expected_minutes:.0f} mins projected). Minutes are the foundation everything "
                f"else sits on: the best underlying numbers in the league score nothing from the bench."
            )
        if p_start >= 0.6:
            return (
                f"⏱️ Usually starts ({p_start * 100:.0f}% of games, {expected_minutes:.0f} mins "
                f"projected) — some rotation risk, so worth a team-news check before the deadline."
            )
        return (
            f"⚠️ **Rotation risk** — starts only {p_start * 100:.0f}% of the time "
            f"({expected_minutes:.0f} mins projected). Their per-90 rate may look good, but they "
            f"have to be on the pitch to use it."
        )
    return None


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


def _supporting_data(row: pd.Series) -> str:
    """One tight line of numbers that back the argument up.

    Deliberately one line. The writeups used to stack a projection, a form
    reading, an xGI figure, an average FDR, a minutes percentage, transfer
    momentum and an ICT score on top of each other, which buries the
    actual reason to pick someone under a readout nobody asked for. The
    case for a player is a sentence you could say out loud; the numbers
    are there to check it, not to be it.
    """
    bits = [f"£{row['price']:.1f}m"]

    xp_next = row.get("xp_next")
    if xp_next is not None and pd.notna(xp_next):
        bits.append(f"{xp_next:.1f} pts projected")

    ownership = row.get("selected_by_percent")
    if ownership is not None and pd.notna(ownership):
        bits.append(f"{ownership:.0f}% owned")

    difficulty = row.get("fixture_run_difficulty")
    if difficulty is not None and pd.notna(difficulty):
        bits.append(f"{_difficulty_label(difficulty)} fixtures")

    if row.get("scoring_basis") != "preseason":
        form = row.get("form")
        if form is not None and pd.notna(form) and form > 0:
            bits.append(f"form {form:.1f}")

    return " · ".join(bits)


def _numbers_only_case(row: pd.Series) -> str:
    """The argument for a player nobody has written about this week.

    Still framed as a case rather than a stat list -- most of the squad
    won't appear in expert coverage, and those players still need a reason
    attached to them, not an apology for the absence of one.
    """
    name = row["web_name"]
    position = row.get("position")
    difficulty = row.get("fixture_run_difficulty", 3.0)
    attacking = position in ("MID", "FWD")

    if row.get("scoring_basis") == "preseason":
        return (
            f"No analyst has singled {name} out this week, so this is the model's own call. The "
            f"argument is that the market has already priced their expected role and quality, and "
            f"the fixtures agree: {_fixture_clause(difficulty, attacking)}."
        )

    if attacking:
        xgi = row.get("expected_goal_involvements", 0)
        return (
            f"No analyst has singled {name} out this week, so this is the model's own call. The "
            f"case is that {xgi:.1f} expected goal involvements says the chances are being created "
            f"repeatedly rather than fluked once, and {_fixture_clause(difficulty, True)}."
        )

    xgc = row.get("expected_goals_conceded", 0)
    return (
        f"No analyst has singled {name} out this week, so this is the model's own call. The case is "
        f"that {xgc:.2f} expected goals conceded points to a side that limits chances by structure "
        f"rather than luck, and {_fixture_clause(difficulty, False)}."
    )


def player_rationale(row: pd.Series, report_text: str | None = None) -> str:
    """The written case for picking this player.

    Leads with what analysts actually said and why, because that is the
    reasoning a manager can act on and argue with. Numbers support the
    argument on a single line underneath rather than crowding it out.
    """
    name = row["web_name"]
    team = row["team_short_name"]
    parts = []

    verdict = row.get("consensus_verdict")
    headline = f"**{name}** ({team}) — "
    if verdict and pd.notna(verdict):
        parts.append(headline + str(verdict))
    else:
        parts.append(headline.rstrip("— ").strip())

    consensus_note = consensus_verdict(row)
    if consensus_note:
        parts.append(consensus_note)
    else:
        # Fall back to this week's written report, then to the model's own
        # reasoning -- in that order, because a human's sentence about a
        # player beats a template every time.
        mention = _report_mention(row, report_text)
        parts.append(f"**What managers are saying:** {mention}" if mention else _numbers_only_case(row))

    risk = row.get("consensus_watch_out")
    if risk and pd.notna(risk):
        parts.append(f"**The case against:** {risk}")

    set_pieces = set_piece_note(row)
    if set_pieces:
        parts.append(set_pieces)

    availability = _risk_note(row)
    if availability:
        parts.append(availability)

    parts.append(f"*{_supporting_data(row)}*")
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

    captain_consensus = consensus_verdict(captain_row)
    if captain_consensus:
        parts.append(captain_consensus)

    xp_next = captain_row.get("xp_next")
    if xp_next is not None and pd.notna(xp_next):
        parts.append(
            f"On the numbers: **{xp_next:.1f} projected points, doubled to "
            f"{xp_next * 2:.1f}**. Note the armband is ranked on *ceiling*, not average — a "
            f"defender and a forward projected the same aren't equal bets once you double them, "
            f"because the forward can return 15+ on a two-goal afternoon and the defender's "
            f"realistic best is a clean sheet plus bonus."
        )

    captain_set_pieces = set_piece_note(captain_row)
    if captain_set_pieces:
        parts.append(captain_set_pieces)

    captain_mention = _report_mention(captain_row, report_text)
    if captain_mention:
        parts.append(f'**What FPL managers & analysts are saying about {c_name}:** {captain_mention}')
    vice_mention = _report_mention(vice_row, report_text)
    if vice_mention:
        parts.append(f'**On the vice, {v_name}:** {vice_mention}')
    return "\n\n".join(parts)

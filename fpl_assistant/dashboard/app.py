"""FPL Assistant Manager — weekly Streamlit dashboard.

Run with: streamlit run fpl_assistant/dashboard/app.py
"""
import os
import sys
from pathlib import Path

# Allow `streamlit run` to find the package when launched from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import requests
import streamlit as st

from fpl_assistant import api
from fpl_assistant.analysis import (
    ask as ask_engine,
    captaincy,
    accuracy,
    captain_call,
    odds as odds_module,
    chips,
    consensus,
    decision_set as decision_set_analysis,
    provenance,
    explain,
    optimiser,
    price,
    form,
    fixtures as fixtures_analysis,
    injuries,
    my_squad as my_squad_analysis,
    history,
    matchups,
    omissions,
    planner,
    scenarios,
    gameweek_state,
    snapshots,
    search as research_search,
    rationale,
    squad_builder,
    team_brief,
    transfer_case,
    transfers,
)
from fpl_assistant.analysis.season_state import is_preseason
from fpl_assistant.config import FPL_TEAM_ID
from fpl_assistant.dashboard.cards import SCORE_BAD, SCORE_WARN, player_rank_card, render_rank_card_list
from fpl_assistant.dashboard.htmlutil import render_html
from fpl_assistant.dashboard.media import player_photo_html
from fpl_assistant.dashboard.pitch import render_pitch_html
from fpl_assistant.dashboard.styles import fdr_color, hero_header, inject_global_css, section_header
from fpl_assistant.models import (
    Squad,
    SquadPick,
    attach_team_names,
    events_df,
    fixtures_df,
    parse_squad,
    players_df,
    teams_df,
)
from fpl_assistant.reports import load_report

st.set_page_config(page_title="FPL Assistant Manager", layout="wide")

FIXTURE_WINDOW = 6


@st.cache_data(ttl=600)
def load_core_data():
    bootstrap = api.get_bootstrap_static()
    fixtures_raw = api.get_fixtures()
    players = attach_team_names(players_df(bootstrap), teams_df(bootstrap))
    teams = teams_df(bootstrap)
    events = events_df(bootstrap)
    fixtures = fixtures_df(fixtures_raw)
    # NOT api.current_event: the API calls a gameweek "current" from its
    # deadline until its last match finishes, so through the whole weekend
    # it kept pointing at a gameweek nobody could still change their team
    # for -- and the page recomputed that gameweek's advice against stats
    # updating live. Deadlines decide what's plannable; results decide
    # what's finished.
    state = gameweek_state.resolve(events, fixtures)
    return players, teams, events, fixtures, state


@st.cache_data(ttl=600, show_spinner=False)
def cached_scores(players, fixtures, teams, next_event):
    """Projections, computed once per data refresh.

    Streamlit re-executes the entire script on every interaction — every
    tab click, every radio change, every keystroke that submits. Without
    this, projecting the whole player pool and solving the squad ran four
    separate times per interaction, about three seconds of identical work
    for a result that hadn't changed. Caching is what makes the app feel
    like an app rather than a form submission.
    """
    return squad_builder.score_players(players, fixtures, teams, next_event)


@st.cache_data(ttl=600, show_spinner=False)
def cached_solution(scored, template_weight):
    """The solved squad. Keyed on the rank strategy, so moving that slider
    re-solves — and nothing else does."""
    return squad_builder.recommend_squad(scored, template_weight=template_weight)


@st.cache_data(ttl=1800, show_spinner=False)
def cached_matchups(gameweek):
    """This gameweek's fixture-level commentary, read once per refresh."""
    return matchups.load(int(gameweek))


@st.cache_data(ttl=600, show_spinner=False)
def cached_multiweek_plan(scored, owned_ids, bank, free_transfers, horizon):
    """The multi-gameweek schedule.

    Cached hard, and separately from the single-week plan, because it is
    the most expensive thing the app does — a few seconds of branch and
    bound rather than the fraction of a second the weekly solve takes.
    Without this it would re-solve on every tab click.
    """
    names = dict(zip(scored["id"], scored["web_name"]))
    return planner.plan_transfers(
        scored,
        list(owned_ids),
        bank=bank,
        free_transfers=free_transfers,
        horizon=horizon,
        names=names,
    )


@st.cache_data(ttl=3600, show_spinner=False)
def cached_track_record(positions, averages, gameweeks):
    """Scores every finished gameweek that has a snapshot.

    An hour's TTL rather than ten minutes: results stop changing once the
    bonus points settle, and each gameweek costs a live-endpoint fetch.
    """
    scores = accuracy.score_history(
        list(gameweeks),
        api.get_event_live,
        positions=dict(positions),
        averages=dict(averages),
    )
    return scores, accuracy.calibrate(scores)


RANK_STRATEGIES = {
    "Balanced": (
        optimiser.TEMPLATE_WEIGHT,
        "Follows the projections, with a nudge toward near-universal picks so one big haul can't "
        "quietly cost you thousands of ranks.",
    ),
    "Protect my rank": (
        optimiser.TEMPLATE_WEIGHT * 4,
        "Shadows the template. You'll rarely gain ground fast, but you also won't be the manager "
        "who missed the 70%-owned captain's hat-trick.",
    ),
    "Chase rank (differentials)": (
        -optimiser.TEMPLATE_WEIGHT * 3,
        "Actively favours low-owned players. Higher variance both ways — the right approach if you "
        "need to make up a lot of ground and a safe finish is worth nothing to you.",
    ),
}


def rank_strategy_weight() -> float:
    """Reads the sidebar's rank-strategy choice.

    Maximising expected points and maximising rank aren't the same problem:
    if a 70%-owned player hauls, everyone who faded him drops together,
    even where fading him was the higher expected-points call. Which side
    of that you want to be on depends on whether you're protecting a good
    rank or chasing one, and only the user knows that — so it's a control,
    not a constant.
    """
    choice = st.session_state.get("rank_strategy", "Balanced")
    return RANK_STRATEGIES.get(choice, RANK_STRATEGIES["Balanced"])[0]


def render_rank_strategy_control() -> None:
    st.sidebar.markdown("---")
    st.sidebar.subheader("🎯 Rank strategy")
    choice = st.sidebar.radio(
        "How much risk do you want?", list(RANK_STRATEGIES), key="rank_strategy",
        label_visibility="collapsed",
    )
    st.sidebar.caption(RANK_STRATEGIES[choice][1])


CONSENSUS_LABELS = {
    "must_have": ("✅ Must-have", "Locked into the squad"),
    "strong": ("👍 Widely backed", "Heavily weighted in selection"),
    "value": ("💡 Popular value pick", "Given a selection bonus"),
    "avoid": ("🚫 Avoid", "Excluded from selection"),
}


def _research_freshness(next_event) -> str | None:
    """A plain-language age for the research, or None if undated."""
    from datetime import date

    stamp = consensus.researched_on(next_event)
    if not stamp:
        return None
    try:
        researched = date.fromisoformat(stamp)
    except ValueError:
        return None
    days = (date.today() - researched).days
    if days <= 0:
        return "researched today"
    if days == 1:
        return "researched yesterday"
    if days <= 4:
        return f"researched {days} days ago"
    return (
        f"⚠️ researched {days} days ago — injuries, lineups and prices will have moved since, "
        f"so re-check anything that looks decisive"
    )


def render_consensus_panel(scored, squad, next_event) -> None:
    """Shows what the experts said and exactly what the app did about it.

    The consensus now moves the selection, so it has to be visible and
    auditable — otherwise the squad reads as arbitrary and there's no way
    to tell whether the app actually acted on the research.
    """
    matched = consensus.summary(scored)
    if matched.empty:
        st.caption(
            "No expert consensus file for this gameweek yet, so this squad is projection-only. "
            "Ask in the sidebar and I'll research the week and fold it in."
        )
        return

    in_squad = set(squad["id"])
    with st.expander("🗣️ What the experts are saying — and what this squad did about it", expanded=True):
        freshness = _research_freshness(next_event)
        st.caption(
            "Consensus is an input to the algorithm, not a footnote: must-haves are locked in, "
            "and the rest carry a weighted bonus that competes directly against the projection."
            + (f"  \n{freshness}." if freshness else "")
        )
        for _, row in matched.iterrows():
            label, effect = CONSENSUS_LABELS.get(row["consensus_tier"], ("—", ""))
            picked = "**In your squad**" if row["id"] in in_squad else "not selected"
            st.markdown(
                f"{label} · **{row['web_name']}** (£{row['price']:.1f}m) — {picked}  \n"
                f"<span style='opacity:0.75'>{row['consensus_reason']}</span>  \n"
                f"<span style='opacity:0.55;font-size:0.85em'>Effect on selection: {effect}</span>",
                unsafe_allow_html=True,
            )
            render_evidence(consensus.key_stats(row), consensus.voices(row))
            dissent = row.get("consensus_dissent")
            if dissent is not None and pd.notna(dissent):
                # Shown rather than averaged away. A contested pick presented
                # with the same confidence as a unanimous one is the app
                # sounding surer than the evidence supports.
                st.markdown(
                    f"<span style='opacity:0.7;font-size:0.9em'>⚖️ <b>But not everyone agrees.</b> "
                    f"{dissent}</span>  \n"
                    f"<span style='opacity:0.5;font-size:0.8em'>Because this one is contested, his "
                    f"weighting is damped rather than applied in full.</span>",
                    unsafe_allow_html=True,
                )
            st.markdown("")


def provenance_chip(row, next_event) -> str:
    """A one-glance marker of what's actually behind this player."""
    mark = provenance.for_player(row, next_event)
    colours = {
        provenance.FRESH: ("#1a6b3c", "#e9f7ef"),
        provenance.STALE: ("#8a6100", "#fdf4e3"),
        provenance.NUMBERS: ("#5f5a6b", "#f4f2f8"),
    }
    fg, bg = colours[mark.level]
    return _chip(f"{mark.icon} {mark.label}", fg, bg)


def render_coverage_panel(scored, player_ids, next_event) -> None:
    """How much of what you're being told is researched, and what isn't.

    The honest version of "how much should I trust this". A squad where
    every pick has named sources behind it and one where half of it is
    arithmetic look the same otherwise, and they shouldn't.
    """
    counts = provenance.summarise(scored, player_ids, next_event)
    total = sum(counts.values()) or 1
    fresh, stale, numbers = counts[provenance.FRESH], counts[provenance.STALE], counts[provenance.NUMBERS]

    bar = "".join(
        f"<span style='display:inline-block;height:8px;width:{count / total * 100:.1f}%;"
        f"background:{colour}'></span>"
        for count, colour in (
            (fresh, "#3aa76d"), (stale, "#e0b23c"), (numbers, "#d8d4e2")
        ) if count
    )
    render_html(
        f"<div style='margin:2px 0 6px 0;border-radius:4px;overflow:hidden;line-height:0'>{bar}</div>"
        f"<div style='font-size:.82em;opacity:.7'>"
        f"<b>{fresh}</b> researched this week · <b>{stale}</b> from earlier · "
        f"<b>{numbers}</b> on the numbers alone</div>"
    )
    if numbers > total / 2:
        st.caption(
            "More than half of this squad has no analyst coverage behind it. The projection is "
            "still doing its job, but run `/refresh` in Claude Code before the deadline if you "
            "want the reasoning to be as good as the arithmetic."
        )


def render_evidence(stats, voices, sources=None) -> None:
    """The numbers and the quotes, shown as numbers and quotes.

    Deliberately not folded into the surrounding prose. A paragraph that
    says "strong underlying numbers and analysts are keen" is unarguable
    in the bad sense -- you can't check it, you can't disagree with a
    specific part of it, and you can't tell whether it was written from
    evidence or from a template. Discrete facts with named sources can be
    checked line by line, which is the only version of this worth reading.
    """
    if stats:
        st.markdown(
            "<div style='opacity:0.85;font-size:0.9em;line-height:1.75'>"
            + "".join(
                f"<span style='display:inline-block;background:#f2f0f7;border:1px solid #e3dff0;"
                f"border-radius:6px;padding:1px 8px;margin:0 5px 5px 0'>{stat}</span>"
                for stat in stats
            )
            + "</div>",
            unsafe_allow_html=True,
        )
    for source, take in voices or []:
        st.markdown(
            f"<div style='margin:5px 0 0 0;padding-left:10px;border-left:2px solid #e3dff0'>"
            f"<span style='font-weight:600;font-size:0.85em'>{source}</span><br>"
            f"<span style='opacity:0.8;font-size:0.9em'>{take}</span></div>",
            unsafe_allow_html=True,
        )
    if sources:
        st.markdown(
            f"<span style='opacity:0.45;font-size:0.8em'>Sources: {sources}</span>",
            unsafe_allow_html=True,
        )


OMISSION_STYLE = {
    "club": ("🚫", "Club-wide expert verdict"),
    "expert": ("🗣️", "Expert avoid"),
    "disputed": ("⚖️", "Experts disagree"),
    "unavailable": ("🏥", "Not available"),
    "cost": ("💸", "Squeezed out by the budget"),
}


@st.cache_data(ttl=900, show_spinner=False)
def cached_omissions(scored, _solution, template_weight, cache_key):
    """Counterfactual solves are ILPs, so this is cached like the main one.

    `_solution` is passed with a leading underscore so Streamlit skips
    hashing it, and `cache_key` carries the identity instead. The real
    solution has to go through rather than a reconstructed stand-in: the
    cost of adding a player is measured as the difference between the
    re-solved squad and this one, so a stand-in with a zeroed
    `expected_points` reports the entire squad's score as the price of one
    transfer -- "costs ~205 points to fit in", stated with total
    confidence. A number that wrong is worse than no number.
    """
    return omissions.notable_omissions(scored, _solution, template_weight=template_weight)


def render_omissions_panel(scored, solution) -> None:
    """Why the players you expected to see aren't here.

    A squad view answers "who?" and silently declines to answer "why not
    him?". From the outside, a player the app weighed and rejected looks
    exactly like a player it never considered, and that ambiguity is where
    trust in the whole recommendation goes -- you spot a name half the
    game owns, can't tell which happened, and stop believing the fifteen.
    """
    try:
        found = cached_omissions(
            scored, solution, rank_strategy_weight(),
            cache_key=(tuple(solution.squad_ids), round(solution.expected_points, 3)),
        )
    except Exception as exc:  # a counterfactual failing must not take the page down
        st.caption(f"Couldn't work out the notable omissions this week ({exc}).")
        return
    if not found:
        return

    with st.expander("🙅 Who we're NOT picking — and why", expanded=True):
        st.caption(
            "The popular and highly-rated players this squad leaves out, with the actual reason. "
            "A player the algorithm weighed and rejected should never look the same as one it "
            "never considered."
        )
        for item in found:
            icon, label = OMISSION_STYLE.get(item.category, ("•", ""))
            meta = f"{item.team} · {item.position} · £{item.price:.1f}m"
            if item.ownership >= 1:
                meta += f" · {item.ownership:.0f}% owned"
            if item.points_cost is not None:
                meta += f" · costs ~{item.points_cost:.1f} pts to fit in"

            st.markdown(
                f"{icon} **{item.headline}**  \n"
                f"<span style='opacity:0.55;font-size:0.85em'>{label} · {meta}</span>  \n"
                f"<span style='opacity:0.8'>{item.detail}</span>",
                unsafe_allow_html=True,
            )
            if item.swaps:
                swap = item.swaps[0]
                st.markdown(
                    f"<span style='opacity:0.55;font-size:0.85em'>To fit him: "
                    f"{swap.out_name} (£{swap.out_price:.1f}m) → {swap.in_name} "
                    f"(£{swap.in_price:.1f}m)</span>",
                    unsafe_allow_html=True,
                )
            # The objections in people's own words, before the numbers.
            # "Why isn't he in the squad" is nearly always better answered
            # by what the community is saying than by a points gap.
            if item.against:
                for point, source in item.against:
                    attribution = f" *— {source}*" if source else ""
                    st.markdown(f"  - {point}{attribution}")
            render_evidence(item.stats, item.voices, item.sources)
            st.markdown("")


FACTOR_GROUPS = {
    "Attacking output": [
        "Expected goals and assists per 90 — underlying rate, not goals already scored, because "
        "finishing over a few games is mostly noise while shot volume persists",
        "Penalty duty — the biggest ceiling swing that's invisible in price or form",
        "Set-piece duty (corners, direct free-kicks) — a repeatable assist source",
    ],
    "Minutes — the foundation everything else sits on": [
        "Start rate and minutes played — a brilliant rate off the bench scores nothing",
        "Injury and availability flags, graded rather than binary",
        "European football: midweek travel means rotation, and the Europa League costs more than "
        "the Champions League because Thursday leaves two fewer recovery days",
        "New managers — an unsettled XI shuffles squad players more",
        "Yellow-card accumulation — a ban carries no injury flag, because the player is fit",
    ],
    "Defensive and other scoring": [
        "Expected goals conceded → clean-sheet probability, floored at a realistic rate",
        "Goalkeeper save rate, defensive contributions, bonus-point history, cards",
    ],
    "Fixtures": [
        "Opponent strength applied directionally — a striker's fixture is easy when the opponent "
        "defends badly, a defender's when the opponent attacks badly",
        "Home advantage, double gameweeks counted twice, blanks counted as zero",
        "Later gameweeks discounted, since you can transfer before they arrive",
    ],
    "Selection and strategy": [
        "Budget, position quotas and the three-per-club cap as hard constraints, solved exactly",
        "Bench weighted low — points come from the eleven who start",
        "Captaincy ranked on ceiling rather than average, since the armband doubles a result",
        "Ownership and rank risk, tunable in the sidebar",
        "Expert consensus, weighted directly into the objective",
        "Club-wide expert verdicts — when analysts say to avoid a club until its fixtures turn, "
        "that applies to every player at the club, not just the ones an article named, and it "
        "expires on its own once the run it described has been played",
        "Splits in expert opinion — where reputable analysts argue the opposite case, the pick's "
        "weighting is damped rather than presented as settled",
        "Transfer hits priced in — a move only appears if it beats its own 4-point cost",
        "Roll vs use — this week's best move weighed against two moves next week",
        "Chip timing — doubles for Triple Captain and Bench Boost, blanks for Free Hit, and the "
        "Wildcard judged by re-solving and measuring the gap",
        "Price pressure — net transfers relative to ownership, so team value compounds into "
        "budget for better players later",
    ],
}


def render_factor_panel() -> None:
    """What the model actually weighs, stated so it can be argued with.

    Every line here is covered by a sensitivity test that changes one
    input and asserts the projection moves — a factor that's documented
    but silently cancelled downstream is worse than one that's absent,
    because it looks handled.
    """
    with st.expander("🧠 What this considers when picking a squad"):
        for group, factors in FACTOR_GROUPS.items():
            st.markdown(f"**{group}**")
            for factor in factors:
                st.markdown(f"- {factor}")
        st.caption(
            "Known gaps, stated plainly: transfers are planned one or two gameweeks ahead rather "
            "than across a whole season, and the expert consensus is hand-researched each week — "
            "the maths is tested, the football facts behind it aren't. If a verdict here looks "
            "wrong to you, it's the research that's wrong, not the algorithm ignoring it."
        )


CHIP_ICONS = {
    "Wildcard": "🃏", "Bench Boost": "🪑", "Triple Captain": "👑", "Free Hit": "⚡",
}


def render_chips_tab(players, fixtures, teams, next_event):
    """Chip timing — the biggest points lever in the game.

    Four chips a season, each worth 15-30 points played into the right
    gameweek and close to nothing played into a random one, so the whole
    decision is timing. Every recommendation here reads off the fixture
    schedule rather than off form, because that's what actually decides it.
    """
    section_header(
        f"Chip strategy — GW{next_event}",
        "When to play each one, and — just as often — why to hold",
    )

    scored = cached_scores(players, fixtures, teams, next_event)
    solution = cached_solution(scored, rank_strategy_weight())

    st.caption(
        "Based on the recommended squad. Chips are judged against the fixture schedule ahead — "
        "doubles for Triple Captain and Bench Boost, blanks for Free Hit — and, for the Wildcard, "
        "against how far your squad has drifted from the best one available."
    )

    advice = chips.advise_all(
        scored, solution, fixtures, from_event=next_event,
        template_weight=rank_strategy_weight(),
    )

    for item in advice:
        icon = CHIP_ICONS.get(item.chip, "🎫")
        badge = (
            '<span class="pill pill-good">Act on this</span>' if item.urgent
            else '<span class="pill pill-accent">Hold</span>'
        )
        render_html(
            f'<div style="display:flex;align-items:center;gap:10px;margin:18px 0 6px 0;">'
            f'<span style="font-size:20px">{icon}</span>'
            f'<span style="font-size:17px;font-weight:700">{item.chip}</span>{badge}</div>'
        )
        st.markdown(item.recommendation)
        for line in item.detail:
            st.markdown(line)

    st.markdown("---")
    st.caption(
        "Chips don't roll over between halves of the season, so an unplayed chip is worth zero. "
        "But playing one early to avoid wasting it usually costs more than waiting — doubles and "
        "blanks cluster later, and that's when these earn their keep."
    )


def render_price_panel(players) -> None:
    """Price movement — not points, but it compounds into them.

    Every £0.1m gained is budget for a better player later. The signal is
    net transfers relative to how many people own the player, because a
    1%-owned player needs far fewer transfers to move than a 40%-owned one.
    """
    rising, falling = price.movers(players)
    if rising.empty and falling.empty:
        return

    with st.expander("💷 Price watch — who's about to rise or fall"):
        st.caption(
            "Ranked by transfer momentum relative to ownership, which is what actually drives FPL "
            "price changes. Directional rather than a prediction of tonight — the thresholds aren't "
            "published."
        )
        columns = st.columns(2)
        with columns[0]:
            st.markdown("**📈 Rising**")
            if rising.empty:
                st.caption("Nothing moving up sharply.")
            for _, row in rising.iterrows():
                st.markdown(
                    f"- **{row['web_name']}** ({row['team_short_name']}, £{row['price']:.1f}m) — "
                    f"+{row['net_transfers']:,.0f} net"
                )
        with columns[1]:
            st.markdown("**📉 Falling**")
            if falling.empty:
                st.caption("Nothing dropping sharply.")
            for _, row in falling.iterrows():
                st.markdown(
                    f"- **{row['web_name']}** ({row['team_short_name']}, £{row['price']:.1f}m) — "
                    f"{row['net_transfers']:,.0f} net"
                )
        st.caption(
            "Buy before a rise only if you wanted the player anyway. Chasing price is how people "
            "end up with squads they didn't choose."
        )


def _player_picker_labels(scored) -> dict:
    """Selectable labels -> player id, ordered so the players you'd actually
    ask about are near the top rather than buried in 600 squad fillers."""
    df = scored.sort_values("xp_horizon", ascending=False)
    return {
        f"{row['web_name']} ({row['team_short_name']}, £{row['price']:.1f}m)": row["id"]
        for _, row in df.iterrows()
    }


def _render_answer(answer) -> None:
    st.markdown(answer.headline)
    for line in answer.detail:
        st.markdown(line)

    if answer.swaps:
        for swap in answer.swaps:
            st.markdown(
                f"- **OUT** {swap.out_name} (£{swap.out_price:.1f}m) → "
                f"**IN** {swap.in_name} (£{swap.in_price:.1f}m)"
            )

    # The club verdict goes first when there is one. "Why not him?" is very
    # often not about him at all -- it's that the analysts are avoiding his
    # club until the fixtures turn -- and leading with a points
    # differential while the real reason sits further down the page
    # answers a question nobody asked.
    render_evidence(getattr(answer, "stats", None), getattr(answer, "voices", None))

    if getattr(answer, "club_verdict", None):
        st.markdown(f"**It's his club, not him:** {answer.club_verdict}")
    if answer.consensus_case:
        st.markdown(f"**What analysts say:** {answer.consensus_case}")
    if answer.consensus_against:
        st.markdown(f"**The case against:** {answer.consensus_against}")
    if getattr(answer, "dissent", None):
        st.markdown(f"**Experts disagree here:** {answer.dissent}")


def render_question_box(scored, solution, next_event) -> None:
    """Ask why a player is or isn't picked, and get a computed answer.

    "Why not Bruno?" is answered by forcing him into the squad and solving
    again, so the reply is the actual trade — who drops out and what it
    costs — rather than an opinion about Bruno. A counterfactual you can
    check beats a paragraph you can't.
    """
    section_header("Ask about a pick", "Why him, why not the other guy — answered against this week's numbers")

    labels = _player_picker_labels(scored)
    if not labels:
        return

    question_type = st.radio(
        "What do you want to know?",
        ["Why is / isn't a player picked?", "Compare two players"],
        horizontal=True,
        key="question_type",
    )

    if question_type == "Compare two players":
        columns = st.columns(2)
        left_label = columns[0].selectbox("Player", list(labels), key="compare_left")
        right_label = columns[1].selectbox(
            "…versus", list(labels), index=min(1, len(labels) - 1), key="compare_right"
        )
        if left_label == right_label:
            st.caption("Pick two different players.")
            return
        if st.button("Compare", key="compare_go"):
            _render_answer(explain.compare_players(scored, labels[left_label], labels[right_label]))
        return

    label = st.selectbox("Player", list(labels), key="explain_player")
    if st.button("Explain this pick", key="explain_go"):
        with st.spinner("Re-solving the squad around them…"):
            answer = explain.explain_player(
                scored, solution, labels[label], template_weight=rank_strategy_weight()
            )
        _render_answer(answer)

    st.markdown("**Or just ask**")
    st.caption(
        "Type it however you'd say it — \"why no Bruno?\", \"Salah or Palmer?\", "
        "\"who do I captain?\", \"best value defender\"."
    )
    question = st.text_input(
        "Your question", key="free_question", label_visibility="collapsed",
        placeholder="Why no Bruno?",
    )
    if st.button("Ask", key="free_go", type="primary"):
        if not question.strip():
            st.caption("Type a question first.")
        else:
            with st.spinner("Working it out…"):
                result = ask_engine.ask(
                    question, scored, solution, next_event,
                    template_weight=rank_strategy_weight(),
                )
            if result.source == "engine":
                _render_answer(result.answer)
                st.caption("Answered from this week's numbers — no guesswork, and free.")
            else:
                st.info(result.note)
                st.code(
                    f"FPL question (GW{next_event}): {question.strip()}\n\n{result.text or ''}",
                    language=None,
                )
                st.caption("Copy this (tap the icon) and paste it into your chat with Claude.")


def render_talking_points(row) -> None:
    """The for-and-against, as people actually said it.

    Two columns, both attributed, neither summarised into a bland middle.
    The point is that a manager reads both piles and makes the call — not
    that the app hands down a verdict and hides the argument behind it.
    """
    for_points = consensus.arguments_for(row)
    against_points = consensus.arguments_against(row)
    if not for_points and not against_points:
        return

    left, right = st.columns(2)
    with left:
        st.markdown("**✅ Why people say pick him**")
        if not for_points:
            st.caption("Nothing researched in favour this week.")
        for point, source in for_points:
            attribution = f" *— {source}*" if source else ""
            st.markdown(f"- {point}{attribution}")
    with right:
        st.markdown("**⚠️ Why people say don't**")
        if not against_points:
            st.caption("Nothing researched against this week.")
        for point, source in against_points:
            attribution = f" *— {source}*" if source else ""
            st.markdown(f"- {point}{attribution}")


def render_matchup_notes(row, gameweek) -> None:
    """What people say about the side he is playing, not about him.

    Club-level commentary — "Brighton have the third-best defence in the
    league and press high" — is a fact about every attacker in that
    fixture. Attaching it to the fixture rather than to one write-up is
    what stops the app recommending the other ten as though the
    opposition were neutral.
    """
    club = row.get("team_short_name")
    position = row.get("position")
    if not isinstance(club, str) or not isinstance(position, str):
        return
    try:
        fixtures = cached_matchups(int(gameweek))
    except Exception:
        return

    opposition = matchups.opponent_notes(club, position, fixtures)
    if not opposition:
        return

    fixture = matchups.fixture_for(club, fixtures)
    opponent = fixture.opponent_of(club) if fixture else "the opposition"
    half = "defence" if position in matchups.ATTACKING_POSITIONS else "attack"
    st.markdown(f"**🆚 What people say about the {opponent} {half}**")
    for note in opposition:
        st.markdown(f"- {note.display}")

    mine = matchups.own_notes(club, position, fixtures)
    if mine:
        with st.expander(f"…and about {club} in this fixture"):
            for note in mine:
                st.markdown(f"- {note.display}")


def render_player_deep_dive(row, report_text, fixture_table, fixture_gws, summary=None):
    """One player's full case: photo + rationale text (which already
    surfaces qualitative research from the weekly report) inside an
    expander, with a nested 'Fixtures & form' dropdown for the quant
    detail — shared by Starting XI and Captaincy so both get the same
    depth of treatment.
    """
    summary = summary or f"{row['web_name']} — {row['team_short_name']} · £{row['price']:.1f}m"
    with st.expander(summary):
        photo_col, text_col = st.columns([1, 6])
        with photo_col:
            render_html(
                '<div style="width:56px;height:56px;border-radius:50%;overflow:hidden;">'
                + player_photo_html(
                    row.get("code"), row["web_name"], 56,
                    team_short_name=row.get("team_short_name"),
                )
                + "</div>"
            )
        with text_col:
            st.markdown(
                rationale.player_rationale(
                    row, report_text, team_context=consensus.load_team_context()
                )
            )

        # The reasons people actually give, first and in full.
        #
        # This is the top of the expander on purpose. A projection is a
        # conclusion; these are the arguments, and the arguments are what
        # someone can weigh, disagree with, or act on. Burying them under
        # a number was the single loudest complaint about this app.
        render_talking_points(row)

        # "He usually scores against them" — the first thing anyone says
        # when arguing for a captain, and the thing the API knows nothing
        # about, since it only carries this season and only in aggregate.
        record = row.get("record_vs_opponent")
        if isinstance(record, str) and record.strip():
            render_html(
                "<div style='margin:6px 0 10px 0;padding:10px 12px;background:#fff8e9;"
                "border:1px solid #f0e2c0;border-radius:10px;font-size:.93em'>"
                "<strong>📈 His record against this opponent:</strong> " + record + "</div>"
            )

        render_matchup_notes(row, row.get("_gameweek") or 1)

        # What could actually happen, rather than only what the average
        # is. The same 5.0 projection can be a steady five every week or a
        # blank-blank-fifteen, and those are different players to own.
        try:
            render_html(
                "<div style='margin:2px 0 8px 0;padding:9px 12px;background:#faf9fc;"
                "border:1px solid #e6e2ee;border-radius:10px;font-size:.92em'>"
                + scenarios.narrate(scenarios.outcome_for(row)).replace("**", "")
                + "</div>"
            )
        except Exception:
            pass

        # What he did over full seasons, stated before any of this
        # season's numbers. Two gameweeks in, this is the most informative
        # thing on the page, and burying it under a projection is how the
        # app talked itself into selling a Golden Boot winner.
        prior_seasons = row.get("prior_seasons")
        if isinstance(prior_seasons, str) and prior_seasons.strip():
            render_html(
                "<div style='margin:2px 0 8px 0;padding:9px 12px;background:#f4f7f4;"
                "border:1px solid #dbe6db;border-radius:10px;font-size:.92em'>"
                "<strong>Track record:</strong> " + prior_seasons + "</div>"
            )

        render_html(provenance_chip(row, int(row.get("_gameweek") or 1)))

        # The researched evidence sits directly under the case it supports,
        # so the argument and the thing backing it up are read together
        # rather than the reader having to take the paragraph on trust.
        render_evidence(
            consensus.key_stats(row),
            consensus.voices(row),
            row.get("consensus_sources") if isinstance(row.get("consensus_sources"), str) else None,
        )
        watch_out = row.get("consensus_watch_out")
        if isinstance(watch_out, str) and watch_out.strip():
            st.markdown(f"**The case against:** {watch_out}")
        dissent = row.get("consensus_dissent")
        if isinstance(dissent, str) and dissent.strip():
            st.markdown(f"**⚖️ Experts disagree here:** {dissent}")

        with st.expander("📅 Fixtures & form"):
            team_fixtures = fixture_table.loc[row["team"]]
            fx_row = {f"GW{gw}": team_fixtures[gw] for gw in fixture_gws}
            st.dataframe(pd.DataFrame([fx_row]), width='stretch', hide_index=True)
            st.caption(f"Avg difficulty over the window: {team_fixtures['avg_difficulty']:.1f}/5")

            stats = {"Price": f"£{row['price']:.1f}m", "Ownership": f"{row['selected_by_percent']:.1f}%"}
            if row.get("scoring_basis") != "preseason":
                stats["Form"] = f"{row['form']:.1f}"
                stats["Points/game"] = f"{row.get('points_per_game', 0)}"
                stats["xGI"] = f"{row.get('expected_goal_involvements', 0):.2f}"
                stats["ICT index"] = f"{row.get('ict_index', 0):.1f}"
                stats["Bonus pts"] = f"{row.get('bonus', 0):.0f}"
            stats_df = pd.DataFrame(list(stats.items()), columns=["Stat", "Value"])
            st.dataframe(stats_df, width='stretch', hide_index=True)


def render_live_gameweek_notice(state, scored) -> None:
    """What the app said before the deadline, while that gameweek is played.

    Recomputing a gameweek's advice after kick-off doesn't refresh it, it
    rewrites history: player stats update live, so by Sunday the model
    knows who scored on Saturday and will cheerfully recommend captaining
    a centre-back who already has a goal and a clean sheet. That advice was
    impossible at the only moment it could have been used.

    So during a live gameweek the page says so plainly, shows the frozen
    pre-deadline pick if one was saved, and points every recommendation at
    the gameweek you can still do something about.
    """
    if not state.is_live:
        return

    st.warning(
        f"**GW{state.live_event} is under way** — {state.live_progress}. That deadline has "
        f"gone, so nothing below is a GW{state.live_event} suggestion: everything targets "
        f"**GW{state.planning_event}**, which is the next one you can still change your team "
        f"for. This page will move on by itself once GW{state.live_event}'s last match ends."
    )

    frozen = snapshots.load(state.live_event)
    with st.expander(f"What this app actually suggested before the GW{state.live_event} deadline"):
        if frozen is None:
            st.caption(
                "No pre-deadline snapshot was saved for this gameweek, so there's nothing "
                "honest to show here. It deliberately doesn't reconstruct one from today's "
                "data — that would produce a squad informed by results already in, which is "
                "exactly the problem this exists to avoid."
            )
            return

        st.caption(
            f"Frozen at {frozen.saved_at_display}, before a ball was kicked. Shown unchanged, "
            f"right or wrong — it's the record you can hold this thing to account with."
        )
        names = {int(k): v for k, v in frozen.player_names.items()}

        def _name(pid):
            if pid in scored.index:
                return str(scored.loc[pid, "web_name"])
            return names.get(pid, f"#{pid}")

        cols = st.columns(3)
        cols[0].metric("Formation", frozen.formation)
        cols[1].metric("Captain", _name(frozen.captain_id))
        cols[2].metric("Cost", f"£{frozen.total_cost:.1f}m")
        st.markdown(
            "**XI:** " + ", ".join(_name(pid) for pid in frozen.starting_ids)
            + "  \n**Bench:** " + ", ".join(_name(pid) for pid in frozen.bench_ids)
        )


@st.cache_data(ttl=600, show_spinner=False)
def cached_confirmed_squad(team_id, planning_event):
    return my_squad_analysis.latest_confirmed(team_id, planning_event, api.get_entry_picks)


@st.cache_data(ttl=600, show_spinner=False)
def cached_free_transfers(team_id) -> int:
    try:
        history = api.get_entry_history(team_id)
        return transfers.estimate_free_transfers(history["current"], history["chips"])
    except Exception:
        return 1


def render_player_cases(
    indexed, starting, bench, fixtures, teams, next_event,
    report_text, captain_id=None, vice_id=None,
) -> None:
    """One expandable case per player, starters first.

    Shared by both front-page modes so the from-scratch build and the
    weekly plan can't drift apart on how much they explain.
    """
    fixture_table = fixtures_analysis.team_fixture_table(
        fixtures, teams, next_event, rationale.FIXTURE_WINDOW
    )
    fixture_gws = list(range(next_event, next_event + rationale.FIXTURE_WINDOW))
    next_gw = fixtures_analysis.team_fixture_table(fixtures, teams, next_event, 1)

    for group, players_in_group in (("Starting", starting), ("Bench", bench)):
        if not players_in_group:
            continue
        if group == "Bench":
            st.markdown("**Bench**")
        for pid in players_in_group:
            if pid not in indexed.index:
                continue
            row = indexed.loc[pid].copy()
            # The opponent and the gameweek let the write-up name the
            # fixture rather than describe it as a difficulty rating.
            if row.get("team") in next_gw.index:
                row["opponent"] = next_gw.loc[row["team"], next_event]
            row["_gameweek"] = next_event

            badge = ""
            if pid == captain_id:
                badge = " · 👑 Captain"
            elif pid == vice_id:
                badge = " · Vice"
            summary = (
                f"{row['web_name']} — {row.get('team_short_name','')} · {row['position']} · "
                f"£{row['price']:.1f}m · {row.get('xp_next', 0):.1f} pts{badge}"
            )
            render_player_deep_dive(
                row, report_text, fixture_table, fixture_gws, summary=summary
            )


def render_owned_squad_plan(players, fixtures, teams, next_event, confirmed, state) -> None:
    """The weekly decision, anchored on the squad you actually own.

    From GW2 onward a from-scratch fifteen is not advice, it's a
    description of a squad you can't have: you own fifteen players, you
    have one free transfer, and every extra move costs four points. The
    useful question is much narrower — given what you own, what is the one
    move worth making, and who starts?
    """
    scored = cached_scores(players, fixtures, teams, next_event)
    squad = confirmed.squad
    owned_ids = [p.player_id for p in squad.picks]
    owned = scored[scored["id"].isin(owned_ids)].copy()

    section_header(
        f"Your GW{next_event} plan",
        f"Built from the squad you confirmed in GW{confirmed.event} — not from scratch",
    )

    if state is not None:
        render_live_gameweek_notice(state, scored)

    missing = [pid for pid in owned_ids if pid not in set(scored["id"])]
    if missing:
        st.caption(
            f"{len(missing)} of your players aren't in the projection pool (usually because "
            f"they're flagged unavailable). They're excluded from the XI below."
        )

    free_transfers = cached_free_transfers(squad.team_id)

    metrics = st.columns(4)
    metrics[0].metric("Squad value", f"£{squad.team_value:.1f}m")
    metrics[1].metric("Bank", f"£{squad.bank:.1f}m")
    metrics[2].metric("Free transfers", free_transfers, help="Estimated — check the official page before taking a hit.")
    metrics[3].metric(
        "Projected pts", f"{owned['xp_next'].nlargest(11).sum():.0f}",
        help="Your best legal XI from the players you already own, this gameweek.",
    )

    st.markdown("**How much of this is researched**")
    render_coverage_panel(scored, owned_ids, next_event)

    # An uneven season-history prior silently marks whole positions down,
    # and the only visible symptom is that one position keeps getting
    # sold. Say it out loud rather than letting it look like an opinion.
    try:
        prior_coverage = history.coverage()
        if not prior_coverage.balanced:
            st.warning(prior_coverage.warning)
    except Exception:
        pass

    st.divider()
    plan = render_transfer_plan(
        players, fixtures, teams, next_event, squad, free_transfers, key_prefix="front"
    )
    render_multiweek_plan(
        scored, owned_ids, float(squad.bank or 0.0), free_transfers,
        key_prefix="front_multi", players=players,
    )

    # The suggested squad is the confirmed one with the recommended
    # transfers applied — not a fifteen built from scratch. Showing the
    # pre-transfer eleven under a recommended transfer asks the reader to
    # do the substitution in their head, which is exactly the work the
    # page exists to save them.
    suggested_ids = list(owned_ids)
    if plan is not None and plan.transfers:
        suggested_ids = [i for i in owned_ids if i not in set(plan.out_ids)] + list(plan.in_ids)
    suggested = scored[scored["id"].isin(suggested_ids)].copy()
    if len(suggested) < 11:
        suggested, suggested_ids = owned, list(owned_ids)
    owned, owned_ids = suggested, suggested_ids

    st.divider()
    if plan is not None and plan.transfers:
        st.markdown(f"#### Your suggested XI for GW{next_event}")
        st.caption(
            f"Your confirmed GW{confirmed.event} squad with the transfer above applied — "
            f"not a squad built from scratch. Captaincy is a free decision every week, and "
            f"it's usually worth more than the transfer."
        )
    else:
        st.markdown("#### Your best XI from what you own")
        st.caption(
            f"The strongest legal eleven from your confirmed GW{confirmed.event} fifteen. "
            f"Captaincy is a free decision every week — it's usually worth more than the transfer."
        )

    # A squad carrying injuries can't always field a legal eleven from the
    # players still available, and when it can't, that must not blank the
    # rest of the page. The captaincy call and the per-player cases are
    # still exactly what someone in that position needs -- arguably more
    # so, since they're about to make a transfer.
    starting = bench = []
    formation = None
    captain_id = vice_id = None
    try:
        starting, bench, formation = optimiser.optimise_starting_xi(owned, points_column="xp_next")
        captain_id, vice_id = squad_builder.pick_captain(owned, starting)
    except Exception:
        available = owned.sort_values("xp_next", ascending=False)
        st.warning(
            f"Only {len(owned)} of your fifteen are available and projectable, which isn't "
            f"enough for a legal eleven — FPL will autosub around it. Everything below still "
            f"applies, and the transfer above is the thing worth acting on."
        )
        starting = available["id"].head(11).tolist()
        bench = available["id"].iloc[11:].tolist()
        attackers = available[available["position"].isin(captain_call.ARMBAND_POSITIONS)]
        if len(attackers) >= 2:
            captain_id, vice_id = attackers["id"].iloc[0], attackers["id"].iloc[1]

    xi = optimiser.SquadSolution(
        squad_ids=owned_ids, starting_ids=starting, bench_ids=bench,
        captain_id=captain_id or (starting[0] if starting else 0),
        vice_captain_id=vice_id or (starting[1] if len(starting) > 1 else 0),
        formation=formation or "",
        total_cost=float(owned["price"].sum()),
        expected_points=float(owned.loc[owned["id"].isin(starting), "xp_next"].sum()),
    )

    lookup = owned.set_index("id")
    shape = st.columns(3)
    shape[0].metric("Formation", formation or "—")
    shape[1].metric(
        "Captain", lookup.loc[captain_id, "web_name"] if captain_id in lookup.index else "—"
    )
    shape[2].metric(
        "Vice", lookup.loc[vice_id, "web_name"] if vice_id in lookup.index else "—"
    )

    if captain_id is not None:
        render_html(
            render_pitch_html(owned.set_index("id", drop=False), _squad_from_solution(xi, next_event))
        )

    st.divider()
    # Captaincy is judged over the players you own, since that's the only
    # armband you can actually give out.
    render_captain_call(owned, next_event)

    report_text, _ = load_report(next_event)
    indexed = owned.set_index("id", drop=False)
    if captain_id in indexed.index and vice_id in indexed.index:
        st.markdown(
            rationale.captain_rationale(
                indexed.loc[captain_id], indexed.loc[vice_id], report_text
            )
        )

    # The per-player case. This went missing when the front page became a
    # plan rather than a build, and its absence left the page saying who
    # to start without ever saying why — which is the only part a manager
    # can actually argue with.
    st.divider()
    st.markdown("#### Why each of them")
    render_player_cases(
        indexed, starting, bench, fixtures, teams, next_event,
        report_text, captain_id, vice_id,
    )

    render_question_box(scored, xi, next_event)


def render_starting_xi_tab(players, fixtures, teams, next_event, state=None):
    section_header(f"Recommended Starting XI — GW{next_event}", "Best 15 buildable from scratch, with the case for every starter")

    scored = cached_scores(players, fixtures, teams, next_event)
    solution = cached_solution(scored, rank_strategy_weight())

    if state is not None:
        render_live_gameweek_notice(state, scored)
        if not state.is_live:
            # Freeze this gameweek's advice while its deadline is ahead.
            # Later pre-deadline runs are allowed to replace it -- late
            # team news is when the advice gets better -- but nothing may
            # be written once the gameweek kicks off.
            try:
                snapshots.save(
                    next_event, solution,
                    names={int(pid): str(scored.loc[pid, "web_name"])
                           for pid in solution.squad_ids if pid in scored.index},
                    projected={int(pid): float(scored.loc[pid, "xp_next"])
                               for pid in solution.squad_ids if pid in scored.index},
                    deadline_passed=False,
                )
            except Exception:
                pass
    squad15 = scored[scored["id"].isin(solution.squad_ids)].copy()
    starters, bench = solution.starting_ids, solution.bench_ids
    formation = solution.formation
    captain_id, vice_id = solution.captain_id, solution.vice_captain_id

    if is_preseason(players):
        st.info(
            "No match data exists yet this season, so these projections lean on price, ownership, "
            "set-piece duties and fixture difficulty rather than form — it's a 'who to pick from "
            "scratch' recommendation, not tied to your actual squad. Once real minutes are played "
            "it switches to underlying stats automatically."
        )
    else:
        st.caption(
            "This is the highest projected-points XI buildable from scratch within a £100m budget — "
            "not necessarily who's currently in your squad. Once GW1 unlocks, use My Squad + "
            "Transfers for advice tailored to what you actually own."
        )

    xi_xp = squad15.loc[squad15["id"].isin(starters), "xp_next"].sum()
    captain_bonus = squad15.loc[captain_id, "xp_next"]
    cost = squad15["price"].sum()

    metrics = st.columns(4)
    metrics[0].metric("Projected pts", f"{xi_xp + captain_bonus:.0f}", help="Starting XI plus the captain's doubled score, for this gameweek.")
    metrics[1].metric("Formation", formation)
    metrics[2].metric("Cost", f"£{cost:.1f}m", delta=f"£{100.0 - cost:.1f}m spare", delta_color="off")
    metrics[3].metric("Captain", squad15.loc[captain_id, "web_name"])

    if solution.optimal:
        st.caption(
            "✅ **Provably optimal** — solved exactly, so no other legal 15 within the budget has a "
            "higher projected score. Points are projected per player from expected goals/assists, "
            "minutes, set-piece duty and opponent strength."
        )
    else:
        for note in solution.notes:
            st.warning(note)

    st.markdown("**How much of this is researched**")
    render_coverage_panel(scored, solution.squad_ids, next_event)

    render_consensus_panel(scored, squad15, next_event)
    render_omissions_panel(scored, solution)
    render_factor_panel()

    report_text, _ = load_report(next_event)

    render_html(render_pitch_html(squad15, _squad_from_solution(solution, next_event)))

    render_captain_call(squad15, next_event)

    captain_row = squad15.loc[captain_id]
    vice_row = squad15.loc[vice_id]
    st.markdown(rationale.captain_rationale(captain_row, vice_row, report_text))

    st.markdown("#### Why each starter")
    st.caption("Grouped by position — tap a player to read the full case for starting them.")

    position_reading_order = {"FWD": 0, "MID": 1, "DEF": 2, "GKP": 3}
    position_labels = {"FWD": "Forwards", "MID": "Midfielders", "DEF": "Defenders", "GKP": "Goalkeeper"}
    starters_df = squad15.loc[starters].copy()
    starters_df["_order"] = starters_df["position"].map(position_reading_order)
    starters_df = starters_df.sort_values(["_order", "xp_next"], ascending=[True, False])

    render_player_cases(
        squad15.set_index("id", drop=False), starters, bench, fixtures, teams, next_event,
        report_text, captain_id, vice_id,
    )

    st.markdown("---")
    render_question_box(scored, solution, next_event)

    with st.expander(f"Bench ({', '.join(squad15.loc[bench, 'web_name'])})"):
        bench_cols = ["web_name", "team_short_name", "position", "price"]
        st.caption(
            "Deliberately cheap: points come from the eleven who start, so the optimiser spends "
            "the minimum here to free budget for the XI. Ordered by who comes on first if a "
            "starter doesn't play."
        )
        st.dataframe(squad15.loc[bench, bench_cols], width='stretch')


def render_manual_squad_entry(players: pd.DataFrame):
    """Lets the user tell us their squad directly when the API won't show it
    yet (pre-deadline). Session-only — resets if the page fully reloads.
    """
    st.markdown("#### Enter your squad manually")
    st.caption(
        "You already know your picks from the official app — list them here to see the pitch view "
        "today instead of waiting for the deadline."
    )

    df = players.copy()
    df["label"] = df["web_name"] + " (" + df["team_short_name"] + ", £" + df["price"].round(1).astype(str) + "m)"
    label_to_id = dict(zip(df["label"], df["id"]))

    squad_labels = st.multiselect("Your 15-man squad", sorted(label_to_id), max_selections=15)
    if len(squad_labels) != 15:
        st.caption(f"{len(squad_labels)}/15 selected.")
        return None

    starting_labels = st.multiselect("Which 11 are starting?", squad_labels, max_selections=11)
    if len(starting_labels) != 11:
        st.caption(f"{len(starting_labels)}/11 starters selected.")
        return None

    captain_label = st.selectbox("Captain", starting_labels)
    vice_options = [name for name in starting_labels if name != captain_label]
    vice_label = st.selectbox("Vice-captain", vice_options) if vice_options else None

    bench_labels = [name for name in squad_labels if name not in starting_labels]
    picks = [
        SquadPick(
            label_to_id[name],
            is_captain=(name == captain_label),
            is_vice_captain=(name == vice_label),
            multiplier=1,
            position_order=i + 1,
        )
        for i, name in enumerate(starting_labels)
    ] + [
        SquadPick(label_to_id[name], False, False, 1, 12 + i) for i, name in enumerate(bench_labels)
    ]
    squad_player_ids = [label_to_id[name] for name in squad_labels]
    return Squad(
        team_id=0, event=0, bank=0.0, team_value=players.loc[squad_player_ids, "price"].sum(),
        transfers_made=0, transfers_cost=0, picks=picks,
    )


def _squad_from_solution(solution, next_event) -> Squad:
    """Wraps a solver result in the Squad shape the pitch renderer wants."""
    picks = [
        SquadPick(pid, is_captain=(pid == solution.captain_id),
                  is_vice_captain=(pid == solution.vice_captain_id),
                  multiplier=1, position_order=i + 1)
        for i, pid in enumerate(solution.starting_ids)
    ] + [SquadPick(pid, False, False, 1, 12 + i) for i, pid in enumerate(solution.bench_ids)]
    return Squad(
        team_id=0, event=next_event, bank=0.0, team_value=0.0,
        transfers_made=0, transfers_cost=0, picks=picks,
    )


def render_squad_tab(players: pd.DataFrame, team_id: int, next_event: int, events: pd.DataFrame,
                     fixtures: pd.DataFrame = None, teams: pd.DataFrame = None):
    """The squad you actually own — which, before a deadline, is last week's.

    This used to ask the API for the gameweek being planned, get a 404,
    explain the 404, and offer manual entry. That is technically correct
    and practically useless: FPL doesn't publish a gameweek's squads until
    its deadline passes, so for most of every week this tab showed an
    error instead of the fifteen players you own. The squad you own right
    now IS last gameweek's squad, and that is what belongs here.
    """
    confirmed = None
    try:
        confirmed = cached_confirmed_squad(team_id, next_event)
    except Exception as exc:
        st.error(f"Couldn't load team {team_id}: {exc}")

    if confirmed is None:
        st.info(
            "Couldn't find a confirmed squad for this team yet. FPL only publishes a "
            "gameweek's picks once its deadline has passed, so if you've just started "
            "there may be nothing to show until after your first deadline."
        )
        manual_squad = render_manual_squad_entry(players)
        if manual_squad:
            render_html(render_pitch_html(players, manual_squad))
            return manual_squad
        return

    squad = confirmed.squad
    try:
        entry = api.get_entry(team_id)
    except Exception:
        entry = {}

    if confirmed.is_current:
        section_header(
            f"{entry.get('name', 'Your team')} — GW{confirmed.event}",
            "Confirmed for the gameweek being planned",
        )
    else:
        section_header(
            f"{entry.get('name', 'Your team')} — your GW{confirmed.event} squad",
            f"The last squad FPL has confirmed. This is what you own going into GW{next_event}, "
            f"and it's the base every suggestion on the front page is built from.",
        )

    c1, c2, c3 = st.columns(3)
    c1.metric("Team value", f"£{squad.team_value:.1f}m")
    c2.metric("Bank", f"£{squad.bank:.1f}m")
    c3.metric(
        "Overall rank",
        f"{entry.get('summary_overall_rank', 0):,}" if entry.get("summary_overall_rank") else "—",
    )

    available = [pid for pid in squad.player_ids if pid in players.index]
    squad_players = players.loc[available].copy()

    render_html(render_pitch_html(squad_players, squad))

    squad_players["captain"] = squad_players["id"].apply(
        lambda pid: "C" if pid == squad.captain_id else ""
    )
    cols = ["web_name", "team_short_name", "position", "price", "form", "status_label", "captain"]
    shown = [c for c in cols if c in squad_players.columns]
    with st.expander("Squad detail table"):
        st.dataframe(squad_players[shown].sort_values(["position", "web_name"]), width='stretch')

    return squad


def render_captain_call(scored, next_event) -> None:
    """The armband, with the case, the field, and the disagreement.

    Three things this has to do that a ranked list doesn't: rank on the
    ceiling rather than the mean (the armband doubles, and doubling
    rewards the tail), account for what everyone else is doing (rank moves
    on difference, not on score), and say out loud when the numbers and
    the analysts disagree instead of quietly averaging them.
    """
    try:
        annotated = odds_module.annotate(scored, next_event)
        cases = captain_call.rank(annotated, next_event, strategy=rank_strategy_weight())
    except Exception as exc:
        st.caption(f"Couldn't assess captaincy this week ({exc}).")
        return
    if not cases:
        return

    st.markdown("#### 👑 The armband")
    st.markdown(captain_call.verdict(cases, strategy=rank_strategy_weight()))
    st.caption(
        "Ranked on ceiling rather than average score — the armband doubles a result, so upside "
        "matters more than the mean. Defenders and goalkeepers are excluded: even the "
        "highest-scoring defender in FPL history is a 9/1 shot to score in a given week, which "
        "is what a defensive captaincy ceiling actually looks like."
    )

    for index, case in enumerate(cases[:4]):
        badge = "👑" if index == 0 else f"{index + 1}."
        header = (
            f"{badge} {case.name} ({case.team}) — {case.expected:.1f} projected · "
            f"ceiling {case.ceiling} · {case.p_haul * 100:.0f}% haul"
        )
        with st.expander(header, expanded=index == 0):
            for reason in case.reasons:
                st.markdown(f"- {reason}")
            if case.expert_take:
                st.markdown(f"**What the analysts say:** {case.expert_take}")
            if case.odds_note:
                st.markdown(f"**The market:** {case.odds_note}")
            disagreement = captain_call.adjudicate(case)
            if disagreement:
                st.markdown(disagreement)


def render_captaincy_tab(players, fixtures, teams, next_event):
    section_header(f"Captaincy candidates — GW{next_event}", "Ranked, with photos and the reasoning behind each score")
    picks = captaincy.captaincy_candidates(players, fixtures, teams, next_event)

    if picks.empty:
        st.info("No candidates found — teams with a blank gameweek here are excluded.")
        return

    preseason = is_preseason(players)
    cards = []
    for i, (_, row) in enumerate(picks.iterrows(), start=1):
        if preseason:
            meta = f"£{row['price']:.1f}m · {row['selected_by_percent']:.1f}% owned"
        else:
            meta = f"£{row['price']:.1f}m · form {row['form']:.1f} · {row['expected_goal_involvements']:.1f} xGI"
        meta += f" · vs {row['opponent']}"
        cards.append(player_rank_card(i, row, f"{row['captaincy_score']:.2f}", "score", meta))
    render_html(render_rank_card_list(cards))

    if preseason:
        st.caption(
            "Score is **projected points for this gameweek**, adjusted for ceiling. No match data "
            "exists yet, so the projection leans on price, ownership, set-piece duty and opponent "
            "strength until real minutes are played."
        )
    else:
        st.caption(
            "Score is **projected points for this gameweek**, adjusted for ceiling — built from "
            "expected goals and assists, expected minutes, set-piece duty and opponent strength. "
            "Ceiling-adjusted because the armband doubles a result: a forward and a defender "
            "projected the same aren't equal bets once doubled."
        )

    st.markdown("#### Top picks in depth")
    st.caption("The armband is the single biggest call of the week — full case, community research, and fixtures for the top 3.")

    report_text, _ = load_report(next_event)
    scored = cached_scores(players, fixtures, teams, next_event)
    fixture_table = fixtures_analysis.team_fixture_table(fixtures, teams, next_event, rationale.FIXTURE_WINDOW)
    fixture_gws = list(range(next_event, next_event + rationale.FIXTURE_WINDOW))

    for player_id, cap_row in picks.head(3).iterrows():
        if player_id not in scored.index:
            # squad_builder's scoring window is wider than captaincy's (which
            # only needs next gameweek) -- a team with a blank later in that
            # wider window gets excluded from `scored` even if this pick's
            # very next fixture is fine. Rare, but don't crash on it.
            st.caption(f"{cap_row['web_name']} — see the card above; a blank gameweek later in the window means we can't show the full deep-dive.")
            continue
        row = scored.loc[player_id]
        role = " · Captain pick" if player_id == picks.index[0] else ""
        summary = f"{row['web_name']}{role} — score {cap_row['captaincy_score']:.2f} · vs {cap_row['opponent']}"
        render_player_deep_dive(row, report_text, fixture_table, fixture_gws, summary=summary)


FIXTURE_LABELS = {
    "team_name": "Team",
    "avg_difficulty": "Avg FDR",
    "blank_gameweeks": "Blanks",
    "double_gameweeks": "Doubles",
}


def _present_fixture_table(table, gw_cols):
    """Turns the raw fixture frame into something readable.

    Left alone, it renders the team id as an index, six decimal places on
    the average, snake_case headers, and a column of dashes for any
    gameweek the fixture list doesn't reach yet. All four are noise, and
    together they make the most useful table in the app the least legible.
    """
    columns = ["team_name"] + gw_cols + ["avg_difficulty", "blank_gameweeks", "double_gameweeks"]
    view = table[columns].copy()

    # Drop gameweeks with no published fixtures rather than showing a
    # column of dashes.
    for gw in gw_cols:
        if view[gw].astype(str).str.strip().isin(["-", "", "nan"]).all():
            view = view.drop(columns=[gw])

    view["avg_difficulty"] = pd.to_numeric(view["avg_difficulty"], errors="coerce").round(1)
    labels = dict(FIXTURE_LABELS)
    labels.update({gw: f"GW{gw}" for gw in gw_cols})
    return view.rename(columns=labels).reset_index(drop=True)


STANCE_CHIP = {
    "avoid": ("#b3261e", "#fdeceb", "Analysts say avoid"),
    "caution": ("#8a6100", "#fdf4e3", "Flagged as a risk"),
    "target": ("#1a6b3c", "#e9f7ef", "Analysts recommend"),
}
RUN_CHIP = {
    "easy": ("#1a6b3c", "#e9f7ef", "Kind run"),
    "mixed": ("#5f5a6b", "#f4f2f8", "Mixed run"),
    "hard": ("#b3261e", "#fdeceb", "Hard run"),
}


def _fixture_pills(brief) -> str:
    """The run as coloured pills rather than a table row.

    A row of five cells makes you read left to right and hold the numbers
    in your head. Five coloured pills you take in at a glance, which is
    the entire job of a fixture ticker.
    """
    pills = []
    for label, difficulty in brief.fixtures:
        background = fdr_color(difficulty) if difficulty is not None else ""
        colour = background.replace("background-color:", "").strip(" ;") or "#f4f2f8"
        pills.append(
            f"<span style='display:inline-block;background:{colour};border:1px solid rgba(21,19,26,.08);"
            f"border-radius:6px;padding:2px 8px;margin:0 5px 5px 0;font-size:.85em;"
            f"font-variant-numeric:tabular-nums'>{label}</span>"
        )
    return "<div>" + "".join(pills) + "</div>"


def _chip(text, fg, bg) -> str:
    return (
        f"<span style='display:inline-block;background:{bg};color:{fg};border-radius:999px;"
        f"padding:1px 10px;font-size:.78em;font-weight:700;letter-spacing:.03em'>{text}</span>"
    )


def render_team_briefs(scored, fixtures, teams, next_event) -> None:
    """Club-by-club: the run, who to buy, and what to watch for.

    The fixture table answers "which teams have easy games", which is half
    a decision. It tells you nothing about which player at that club is
    the way in, or that their best asset is carrying a knock. This closes
    that gap so you don't have to go and look somewhere else.
    """
    table = fixtures_analysis.team_fixture_table(fixtures, teams, next_event, FIXTURE_WINDOW)
    gameweeks = list(range(next_event, next_event + FIXTURE_WINDOW))
    briefs = team_brief.build_briefs(scored, table, teams, gameweeks)
    if not briefs:
        return

    st.markdown("#### Club by club")
    st.caption(
        "Ordered by how kind the next five look, so the teams worth shopping at are at the top. "
        "Every line is derived from the live data and the researched verdicts — nothing here is "
        "hand-written per club, so it stays true as the season moves."
    )

    lookup = {b.short_name: b for b in briefs}
    picked = st.selectbox(
        "Jump to a club",
        options=[b.short_name for b in briefs],
        format_func=lambda short: (
            f"{lookup[short].name} — {lookup[short].headline}"
            + (f" ({lookup[short].avg_difficulty:.1f} FDR)" if lookup[short].avg_difficulty else "")
        ),
        key="team_brief_pick",
    )

    for brief in briefs:
        expanded = brief.short_name == picked
        label = f"{brief.name} · {brief.headline}"
        if brief.avg_difficulty is not None:
            label += f" · {brief.avg_difficulty:.1f} FDR"
        with st.expander(label, expanded=expanded):
            chips = []
            fg, bg, text = RUN_CHIP[brief.run_quality]
            chips.append(_chip(text, fg, bg))
            if brief.stance in STANCE_CHIP:
                fg, bg, text = STANCE_CHIP[brief.stance]
                chips.append(_chip(text, fg, bg))
            render_html("<div style='margin-bottom:8px'>" + " ".join(chips) + "</div>")

            render_html(_fixture_pills(brief))

            if brief.stance_case:
                st.markdown(f"**What the analysts say:** {brief.stance_case}")
                if brief.stance_sources:
                    st.markdown(
                        f"<span style='opacity:0.45;font-size:0.8em'>Sources: {brief.stance_sources}</span>",
                        unsafe_allow_html=True,
                    )

            left, right = st.columns(2)
            with left:
                st.markdown("**👍 In their favour**")
                for line in brief.pros or ["Nothing standing out either way."]:
                    st.markdown(f"- {line}")
            with right:
                st.markdown("**👎 Watch out for**")
                for line in brief.cons or ["Nothing flagged."]:
                    st.markdown(f"- {line}")

            if brief.assets:
                st.markdown("**Who to look at here**")
                rows = []
                for asset in brief.assets:
                    rows.append({
                        "Player": asset.name,
                        "Pos": asset.position,
                        "Price": f"£{asset.price:.1f}m",
                        "Owned": f"{asset.ownership:.1f}%",
                        "Next GW": round(asset.xp_next, 1),
                        "Next 5": round(asset.xp_horizon, 1),
                        "Note": ("⚠️ " if asset.flagged else "") + (asset.note or ""),
                    })
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def render_fixtures_tab(players, fixtures, teams, next_event):
    section_header(
        f"Fixtures & team guide — next {FIXTURE_WINDOW} gameweeks",
        "Which clubs to shop at, and who to buy when you get there",
    )
    scored = cached_scores(players, fixtures, teams, next_event)

    ticker_tab, teams_tab = st.tabs(["📊 The ticker", "🔍 Club by club"])
    with teams_tab:
        render_team_briefs(scored, fixtures, teams, next_event)

    with ticker_tab:
        _render_fixture_ticker(fixtures, teams, next_event)


def _render_fixture_ticker(fixtures, teams, next_event):
    st.caption("Green is an easier run. Target the top, fade the bottom.")
    table = fixtures_analysis.team_fixture_table(fixtures, teams, next_event, FIXTURE_WINDOW)
    gw_cols = list(range(next_event, next_event + FIXTURE_WINDOW))

    view = _present_fixture_table(table, gw_cols)
    st.dataframe(
        view.style.map(fdr_color, subset=["Avg FDR"]).format({"Avg FDR": "{:.1f}"}),
        width="stretch", hide_index=True,
    )
    st.caption("↔ Scroll the table sideways if your screen cuts off the later gameweeks.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**✅ Best runs** — target these teams' players")
        best = _present_fixture_table(fixtures_analysis.best_fixture_runs(table), [])
        st.dataframe(
            best.style.map(fdr_color, subset=["Avg FDR"]).format({"Avg FDR": "{:.1f}"}),
            width="stretch", hide_index=True,
        )
    with c2:
        st.markdown("**⚠️ Worst runs** — think twice before buying here")
        worst = _present_fixture_table(fixtures_analysis.worst_fixture_runs(table), [])
        st.dataframe(
            worst.style.map(fdr_color, subset=["Avg FDR"]).format({"Avg FDR": "{:.1f}"}),
            width="stretch", hide_index=True,
        )


def render_watchlist_tab(players):
    section_header("Player watchlist", "Who's trending, who's a bargain, who's under the radar")
    preseason = is_preseason(players)
    position = st.selectbox("Position", [None, "GKP", "DEF", "MID", "FWD"], format_func=lambda x: x or "All")

    render_price_panel(players)

    t1, t2, t3 = st.tabs(["In form", "Best value", "Differentials"])
    with t1:
        df = form.in_form_players(players, position=position)
        meta_fn = (
            (lambda r: f"{r['selected_by_percent']:.1f}% owned")
            if preseason
            else (lambda r: f"£{r['price']:.1f}m · {r['points_per_game']} pts/gw")
        )
        score_fn = (lambda r: f"£{r['price']:.1f}m") if preseason else (lambda r: f"{r['form']:.1f}")
        cards = [
            player_rank_card(i, row, score_fn(row), "price" if preseason else "form", meta_fn(row))
            for i, (_, row) in enumerate(df.iterrows(), start=1)
        ]
        render_html(render_rank_card_list(cards))
    with t2:
        df = form.best_value_players(players, position=position)
        cards = [
            player_rank_card(
                i, row,
                f"{row['selected_by_percent']:.1f}%" if preseason else f"{row['points_per_million']}",
                "owned" if preseason else "pts/£m",
                f"£{row['price']:.1f}m · {row['total_points']} pts",
            )
            for i, (_, row) in enumerate(df.iterrows(), start=1)
        ]
        render_html(render_rank_card_list(cards))
    with t3:
        df = form.differentials(players)
        cards = [
            player_rank_card(
                i, row, f"£{row['price']:.1f}m" if preseason else f"{row['form']:.1f}",
                "price" if preseason else "form",
                f"{row['selected_by_percent']:.1f}% owned"
                + ("" if preseason else f" · £{row['price']:.1f}m"),
            )
            for i, (_, row) in enumerate(df.iterrows(), start=1)
        ]
        render_html(render_rank_card_list(cards))


def _injury_cards(df: pd.DataFrame) -> str:
    cards = []
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        news = str(row.get("news") or "").strip() or "No further detail from FPL yet."
        chance = row["chance_of_playing_next_round"]
        color = SCORE_BAD if chance < 50 else SCORE_WARN
        cards.append(
            player_rank_card(
                i, row, f"{chance:.0f}%", "fit",
                f"£{row['price']:.1f}m · {row['status_label']} — {news}",
                score_color=color,
            )
        )
    return render_rank_card_list(cards)


def render_injuries_tab(players, owned_ids):
    section_header("Injury & availability news", "Straight from FPL's own editorial feed")

    st.markdown("**Your squad**")
    if owned_ids is None:
        st.info("Enter your FPL Team ID (or use manual squad entry in My Squad) to check your own players.")
    else:
        own_flagged = injuries.flagged_players(players, owned_only_ids=owned_ids)
        if own_flagged.empty:
            st.success("Nobody in your squad is flagged.")
        else:
            render_html(_injury_cards(own_flagged))

    with st.expander("Everyone flagged this week"):
        all_flagged = injuries.flagged_players(players)
        render_html(_injury_cards(all_flagged))


HIT_STYLE = {
    "player": ("👤", "Player"),
    "club": ("🏟️", "Club verdict"),
    "report": ("📰", "This week's report"),
}
TIER_CHIP = {
    "must_have": ("#1a6b3c", "#e9f7ef", "Must have"),
    "strong": ("#1a6b3c", "#e9f7ef", "Strong pick"),
    "value": ("#2d5c9e", "#eaf1fb", "Value"),
    "avoid": ("#b3261e", "#fdeceb", "Avoid"),
}

SEARCH_EXAMPLES = ["penalties", "World Cup fitness", "Bournemouth", "clean sheets", "set pieces"]


def render_research_search(scored, report_text, teams) -> None:
    """Search everything the app knows, in one box.

    The research lives in four places -- the per-player consensus, the club
    verdicts, the weekly odds report and the live player data -- and until
    now you could only reach any of it by already knowing which tab it was
    filed under. That's fine reading top to bottom and useless when you
    have a specific question, which is most of the time.

    Deliberately a local index rather than a model call: instant, works
    with no API key, and it cannot invent a fact that isn't in the corpus.
    Every hit shows the text that matched and who said it, so you can
    judge it rather than take it.
    """
    st.markdown("#### 🔎 Search the research")
    st.caption(
        "Player names, clubs, or anything you want to know — penalties, set pieces, injuries, "
        "fixture runs. Searches the expert verdicts, the club-level calls, this week's odds "
        "report and the live player data at once."
    )

    query = st.text_input(
        "Search",
        key="research_search_query",
        placeholder="e.g. who's on penalties, Haaland, World Cup fitness…",
        label_visibility="collapsed",
    )

    if not query.strip():
        chips = " ".join(
            f"<span style='display:inline-block;background:#f4f2f8;border:1px solid #e6e2ee;"
            f"border-radius:999px;padding:2px 11px;margin:0 6px 6px 0;font-size:.85em;"
            f"opacity:.75'>{example}</span>"
            for example in SEARCH_EXAMPLES
        )
        render_html(f"<div style='margin-top:-4px'>Try: {chips}</div>")
        return

    try:
        hits = research_search.search(query, scored=scored, report_text=report_text, teams=teams)
    except Exception as exc:
        st.caption(f"Search failed ({exc}).")
        return

    if not hits:
        st.info(
            f"Nothing in the research mentions “{query}”. The research covers the players "
            "analysts wrote about this week plus every club-level verdict — if you're after "
            "reasoning rather than a lookup, ask it as a question on the Starting XI tab and "
            "the squad gets re-solved to answer it."
        )
        return

    st.caption(f"{len(hits)} result{'s' if len(hits) != 1 else ''} for “{query}”")
    for hit in hits:
        icon, kind_label = HIT_STYLE.get(hit.kind, ("•", hit.kind))
        chips = []
        if hit.tier in TIER_CHIP:
            fg, bg, text = TIER_CHIP[hit.tier]
            chips.append(_chip(text, fg, bg))

        with st.container(border=True):
            render_html(
                f"<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap'>"
                f"<span style='font-weight:700'>{icon} {hit.title}</span>"
                + "".join(chips)
                + f"<span style='opacity:.45;font-size:.8em'>{kind_label}</span></div>"
            )
            if hit.subtitle:
                st.markdown(
                    f"<span style='opacity:.75;font-size:.92em'>{hit.subtitle}</span>",
                    unsafe_allow_html=True,
                )
            for label, text in hit.snippets:
                st.markdown(
                    f"<div style='margin:6px 0 0 0;padding-left:10px;border-left:2px solid #e3dff0'>"
                    f"<span style='font-weight:600;font-size:.82em'>{label}</span><br>"
                    f"<span style='opacity:.82;font-size:.9em'>{text}</span></div>",
                    unsafe_allow_html=True,
                )
            if hit.sources:
                st.markdown(
                    f"<span style='opacity:.45;font-size:.78em'>Sources: {hit.sources}</span>",
                    unsafe_allow_html=True,
                )


def render_report_tab(players, fixtures, teams, next_event):
    section_header(
        f"Odds & expert take — GW{next_event}",
        "Everything the analysts are saying, searchable",
    )
    text, filename = load_report(next_event)
    scored = cached_scores(players, fixtures, teams, next_event)

    search_tab, verdicts_tab, report_tab = st.tabs(
        ["🔎 Search", "🗣️ Expert verdicts", "📰 Odds report"]
    )

    with search_tab:
        render_research_search(scored, text, teams)

    with verdicts_tab:
        render_expert_verdicts(scored, next_event)

    with report_tab:
        if text is None:
            st.info(
                "No odds report yet. Ask Claude to \"refresh the gameweek report\" — it runs live "
                "web searches for current odds and expert/community sentiment and writes it here, "
                "since direct scraping of bookmaker and forum sites isn't reliable or always "
                "allowed. The expert verdicts tab works without it."
            )
        else:
            if filename != f"gw{next_event}.md":
                st.warning(
                    f"Showing the most recent report available ({filename}), not one for "
                    f"GW{next_event} specifically."
                )
            st.markdown(text)


def render_expert_verdicts(scored, next_event) -> None:
    """Every researched verdict, filterable, with the evidence attached.

    The consensus panel on the Starting XI tab only shows what the app
    acted on. This shows the whole research file — including the players
    it decided against — because "what are people saying about X" is a
    question you ask before you have a squad, not after.
    """
    matched = consensus.summary(scored)
    if matched.empty:
        st.caption("No expert research has been matched to this gameweek's player pool yet.")
        return

    freshness = _research_freshness(next_event)
    if freshness:
        st.caption(freshness.capitalize() + ".")

    tiers = [t for t in ["must_have", "strong", "value", "avoid"]
             if (matched["consensus_tier"] == t).any()]
    labels = {
        "must_have": "Must have", "strong": "Strong picks",
        "value": "Value picks", "avoid": "Avoid",
    }
    chosen = st.multiselect(
        "Filter",
        options=tiers,
        default=tiers,
        format_func=lambda t: labels.get(t, t),
        key="verdict_tier_filter",
    )
    positions = sorted(matched["position"].dropna().unique().tolist())
    chosen_positions = st.multiselect(
        "Position", options=positions, default=positions, key="verdict_position_filter"
    )

    view = matched[
        matched["consensus_tier"].isin(chosen) & matched["position"].isin(chosen_positions)
    ]
    if view.empty:
        st.caption("Nothing matches those filters.")
        return

    for _, row in view.iterrows():
        chips = []
        if row["consensus_tier"] in TIER_CHIP:
            fg, bg, text = TIER_CHIP[row["consensus_tier"]]
            chips.append(_chip(text, fg, bg))
        if isinstance(row.get("consensus_dissent"), str):
            chips.append(_chip("Experts disagree", "#8a6100", "#fdf4e3"))

        header = (
            f"{row['web_name']} — {row.get('team_short_name','')} · "
            f"£{row['price']:.1f}m · {row.get('selected_by_percent', 0):.1f}% owned"
        )
        with st.expander(header, expanded=False):
            render_html("<div style='margin-bottom:6px'>" + " ".join(chips) + "</div>")
            if isinstance(row.get("consensus_verdict"), str):
                st.markdown(f"**{row['consensus_verdict']}**")
            if isinstance(row.get("consensus_reason"), str):
                st.markdown(row["consensus_reason"])
            render_evidence(
                consensus.key_stats(row),
                consensus.voices(row),
                row.get("consensus_sources") if isinstance(row.get("consensus_sources"), str) else None,
            )
            if isinstance(row.get("consensus_watch_out"), str):
                st.markdown(f"**The case against:** {row['consensus_watch_out']}")
            if isinstance(row.get("consensus_dissent"), str):
                st.markdown(f"**⚖️ Experts disagree here:** {row['consensus_dissent']}")


def render_transfer_case(case) -> None:
    """One swap, argued rather than asserted.

    Out on the left with what people say is wrong; in on the right with
    what people say is right. Asymmetric on purpose — the question is
    "why this swap", not "rate these two players", and showing both sides
    of both men would be balanced and useless.
    """
    st.markdown(f"#### {case.headline}")
    st.markdown(case.summary)

    left, right = st.columns(2)
    with left:
        st.markdown(f"**⬅️ OUT — {case.out.name}**")
        if case.out.fixture:
            st.caption(case.out.fixture)
        if case.out.reasons:
            for point, source in case.out.reasons:
                st.markdown(f"- {point}" + (f" *— {source}*" if source else ""))
        else:
            st.caption("Nothing specific being said against him — he is the one the numbers can spare.")
        if case.out.opposition:
            st.markdown("*What people say about his opponent:*")
            for note in case.out.opposition:
                st.markdown(f"- {note}")

    with right:
        st.markdown(f"**➡️ IN — {case.into.name}**")
        if case.into.fixture:
            st.caption(case.into.fixture)
        if case.into.reasons:
            for point, source in case.into.reasons:
                st.markdown(f"- {point}" + (f" *— {source}*" if source else ""))
        else:
            st.caption("Nothing researched in his favour this week beyond the projection.")
        if case.into.record:
            st.markdown(f"**📈 His record against them:** {case.into.record}")
        if case.into.opposition:
            st.markdown("*What people say about his opponent:*")
            for note in case.into.opposition:
                st.markdown(f"- {note}")

    st.caption(
        f"{case.into.name} projects {case.gain:+.1f} points on {case.out.name} this gameweek. "
        f"The projection is the tiebreak, not the argument."
    )
    st.markdown("---")


def render_transfer_plan(players, fixtures, teams, next_event, squad, free_transfers, key_prefix="plan"):
    """The actual weekly decision: who to bring in, and whether a hit pays.

    Solved rather than suggested — the 4-point hit is priced into the
    objective, so a move only appears here if it earns more than it costs.
    """
    st.markdown("#### Recommended move")

    projected = cached_scores(players, fixtures, teams, next_event)
    owned_ids = [p.player_id for p in squad.picks]

    # Keyed, because this block now renders in two places -- the front page
    # plan and the Transfers tab. Streamlit derives a widget's identity from
    # its type and parameters, so two identical sliders collide and take the
    # whole page down.
    bank = st.slider(
        "Money in the bank (£m)", 0.0, 10.0, float(squad.bank or 0.0), 0.1,
        help="From your official squad page. Sets what you can afford to spend.",
        key=f"{key_prefix}_bank",
    )
    max_transfers = st.slider(
        "Most transfers to consider", 1, 4, 2,
        help="Each move beyond your free transfers costs 4 points, which is priced in below.",
        key=f"{key_prefix}_max_transfers",
    )

    try:
        plan = optimiser.optimise_transfers(
            projected, owned_ids, bank=bank,
            free_transfers=free_transfers, max_transfers=max_transfers,
            template_weight=rank_strategy_weight(),
        )
    except Exception as exc:
        st.info(f"Couldn't solve a transfer plan this week ({exc}). The review list below still applies.")
        return None

    if not plan.transfers:
        st.success(
            "**Hold.** No transfer gains enough to be worth making this week — including any that "
            "would cost a hit. Rolling the transfer keeps your options open for next week."
        )
        return plan

    columns = st.columns(3)
    columns[0].metric("Transfers", plan.transfers)
    columns[1].metric("Points hit", f"−{plan.points_cost}" if plan.points_cost else "None")
    columns[2].metric(
        "Net projected gain", f"+{plan.net_gain:.1f}",
        help="Gain over fielding your best XI as things stand, after subtracting any hit.",
    )

    # The case for each swap, in words. A transfer line that reads
    # "Smith → Jones, +2.3 projected" tells you what the solver concluded
    # and nothing you can agree or disagree with. The reasons are what
    # make it a recommendation rather than an instruction.
    try:
        cases = transfer_case.explain_plan(
            projected, plan.out_ids, plan.in_ids, next_event
        )
    except Exception:
        cases = []

    if cases:
        for case in cases:
            render_transfer_case(case)
    else:
        indexed = projected.set_index("id")
        for out_id, in_id in zip(plan.out_ids, plan.in_ids):
            out_row, in_row = indexed.loc[out_id], indexed.loc[in_id]
            st.markdown(
                f"**OUT** {out_row['web_name']} ({out_row['team_short_name']}, £{out_row['price']:.1f}m · "
                f"{out_row['xp_next']:.1f} pts projected) → "
                f"**IN** {in_row['web_name']} ({in_row['team_short_name']}, £{in_row['price']:.1f}m · "
                f"{in_row['xp_next']:.1f} pts projected)"
            )

    try:
        roll = optimiser.should_roll_transfer(
            projected, owned_ids, bank=bank, free_transfers=free_transfers,
            template_weight=rank_strategy_weight(),
        )
        icon = "🏦" if roll.recommendation == "Roll it" else "✅"
        st.markdown(f"{icon} **{roll.recommendation}** — {roll.detail}")
    except Exception:
        pass  # advisory only; the plan above still stands

    if plan.points_cost:
        st.caption(
            f"This takes a −{plan.points_cost} hit and still comes out **{plan.net_gain:.1f} points "
            f"ahead** over the next {rationale.FIXTURE_WINDOW} gameweeks — that's the only reason to "
            f"take one. If the gap were smaller, holding would be the better play."
        )
    else:
        st.caption("Within your free transfers, so no points hit.")


def render_multiweek_plan(scored, owned_ids, bank, free_transfers, key_prefix="multi", players=None):
    """The transfer schedule, several gameweeks at a time.

    Shown alongside the weekly move rather than instead of it, because
    they answer different questions and can honestly disagree. The weekly
    solve says "this is the best move available now"; the planner says
    "and here is why making it now is or isn't the right time". When the
    planner recommends holding and the weekly solve finds an upgrade, the
    planner is usually right — it can see the transfer being spent better
    two weeks out, and the weekly solve cannot see two weeks out at all.
    """
    st.markdown("#### The next few gameweeks")

    if players is not None:
        # An injured player you own is dropped from the projection pool, and
        # a planner that can't see him can't plan the transfer that moves
        # him on -- which is the transfer you most need planned.
        scored = planner.with_owned_players(scored, players, owned_ids)

    horizon = st.slider(
        "Gameweeks to plan over", 2, 5, planner.DEFAULT_HORIZON,
        help=(
            "Longer plans stage bigger moves, but every extra week rests on team news "
            "that hasn't happened yet."
        ),
        key=f"{key_prefix}_horizon",
    )

    with st.spinner("Planning the next few gameweeks…"):
        try:
            plan = cached_multiweek_plan(
                scored, tuple(int(i) for i in owned_ids), float(bank),
                int(free_transfers), int(horizon),
            )
        except Exception as exc:
            st.info(
                f"Couldn't build a multi-gameweek plan ({exc}). The single-week "
                "recommendation above still stands."
            )
            return None

    if not plan.weeks:
        return None

    st.success(f"**{plan.headline}**")

    columns = st.columns(3)
    columns[0].metric(
        "Projected over the plan", f"{plan.total_projected:.0f}",
        help="Starting XI plus captain each week, minus any hits, discounted for distance.",
    )
    columns[1].metric(
        "Versus holding", f"{plan.gain:+.1f}",
        help="Against fielding the best XI from your current fifteen every week and making no transfers.",
    )
    columns[2].metric("Hits taken", plan.total_hits or "None")

    for line in plan.schedule:
        st.markdown(f"- {line}")

    for note in plan.reasoning:
        st.caption(note)

    return plan


def render_track_record_tab(players, events):
    """Whether the app's advice has actually been any good.

    Everything else here is a projection. This is the one page that can
    tell you the projections are wrong, which makes it the only page worth
    checking before you trust the rest.
    """
    section_header(
        "Track record",
        "Every recommendation this app froze before a deadline, marked against what happened",
    )

    with st.expander("What am I looking at?"):
        st.markdown(
            "**A snapshot** is a file recording exactly what this app recommended for a "
            "gameweek, written *before* that gameweek's deadline and never touched "
            "afterwards. It exists because player stats update live: by the Sunday of a "
            "gameweek the model can see who scored on the Saturday and will happily "
            "\"recommend\" them — advice that was impossible at the only moment you could "
            "have used it. The snapshot is the version you could actually have acted on.\n\n"
            "**The workflow** is a small job GitHub runs on its own computers every three "
            "hours, for free. It checks whether a deadline is coming up and, if so, writes "
            "and commits that gameweek's snapshot. That's the whole job — it just means "
            "nobody has to remember to open the app at 11pm on a Friday.\n\n"
            "**This page** marks one against the other. Nothing here is reconstructed: a "
            "gameweek with no snapshot is skipped rather than scored, because advice graded "
            "against results it could already see wouldn't mean anything."
        )

    finished = []
    try:
        for event_id, row in events.iterrows():
            if bool(row.get("finished")):
                finished.append(int(event_id))
    except Exception:
        finished = []

    if not finished:
        st.info("No gameweeks have finished yet this season — nothing to mark.")
        return

    averages = {}
    for event_id in finished:
        try:
            average = events.loc[event_id, "average_entry_score"]
            if pd.notna(average):
                averages[event_id] = float(average)
        except Exception:
            continue

    positions = {int(pid): pos for pid, pos in zip(players["id"], players["position"])}

    with st.spinner("Marking past gameweeks…"):
        try:
            scores, report = cached_track_record(
                tuple(sorted(positions.items())),
                tuple(sorted(averages.items())),
                tuple(finished),
            )
        except Exception as exc:
            st.info(f"Couldn't load past results ({exc}).")
            return

    if not scores:
        st.info(
            "No saved recommendations to mark yet. A gameweek only gets scored if the app "
            "wrote a snapshot before its deadline — advice judged against results it could "
            "already see wouldn't mean anything, so gameweeks without one are skipped rather "
            "than reconstructed."
        )
        return

    total = sum(s.xi_points for s in scores)
    beat = [s.vs_average for s in scores if s.vs_average is not None]
    columns = st.columns(4)
    columns[0].metric("Gameweeks marked", len(scores))
    columns[1].metric("Points scored", total)
    if beat:
        columns[2].metric(
            "Versus the average manager", f"{sum(beat):+.0f}",
            help="Total difference against the FPL-wide average score for those gameweeks.",
        )
    columns[3].metric(
        "Captain right", f"{sum(1 for s in scores if s.captain_was_best)}/{len(scores)}",
        help="How often the armband went on the highest scorer in the recommended XI.",
    )

    st.markdown("#### How the projections are holding up")
    st.markdown(report.verdict)
    for note in report.position_notes:
        st.markdown(f"- {note}")
    st.caption(
        "Bias is the average of actual minus projected. A model that is consistently high or "
        "low is miscalibrated but still ranks players correctly, which is all the optimiser "
        "needs. A model that is right on average while being wrong about *which* players is "
        "the worse problem, and that is what the per-position split is for."
    )

    if report.worst_overrated or report.worst_underrated:
        left, right = st.columns(2)
        with left:
            st.markdown("**Most overrated**")
            for player in report.worst_overrated:
                st.markdown(
                    f"- {player.name} — projected {player.projected:.1f}, scored {player.actual}"
                )
            if not report.worst_overrated:
                st.caption("Nothing badly overrated.")
        with right:
            st.markdown("**Most underrated**")
            for player in report.worst_underrated:
                st.markdown(
                    f"- {player.name} — projected {player.projected:.1f}, scored {player.actual}"
                )
            if not report.worst_underrated:
                st.caption("Nothing badly underrated.")

    st.markdown("#### Gameweek by gameweek")
    for score in sorted(scores, key=lambda s: -s.gameweek):
        header = f"GW{score.gameweek} — {score.xi_points} points"
        if score.vs_average is not None:
            header += f" ({score.vs_average:+.0f} vs average)"
        with st.expander(header, expanded=score.gameweek == max(s.gameweek for s in scores)):
            st.markdown(score.verdict)
            table = pd.DataFrame(
                [
                    {
                        "Player": p.name,
                        "Pos": p.position,
                        "In XI": "✓" if p.started else "",
                        "C": "👑" if p.captain else "",
                        "Projected": p.projected,
                        "Actual": p.actual,
                        "Miss": p.error,
                    }
                    for p in sorted(score.players, key=lambda p: (not p.started, -p.actual))
                ]
            )
            st.dataframe(table, width='stretch', hide_index=True)
            st.caption(
                f"The XI was projected to score {score.projected_xi:.1f} and scored "
                f"{score.xi_points} ({score.projection_error:+.1f})."
            )


def render_transfers_tab(players, fixtures, teams, next_event, squad):
    section_header("Transfer suggestions")

    free_transfers = 1
    try:
        history = api.get_entry_history(squad.team_id)
        free_transfers = transfers.estimate_free_transfers(history["current"], history["chips"])
        st.metric("Estimated free transfers", free_transfers)
        st.caption("Approximate — verify against the official squad page before taking a hit.")
    except Exception:
        pass  # not critical to the rest of the tab

    render_transfer_plan(players, fixtures, teams, next_event, squad, free_transfers)

    st.markdown("---")
    render_multiweek_plan(
        cached_scores(players, fixtures, teams, next_event),
        [p.player_id for p in squad.picks],
        float(squad.bank or 0.0),
        free_transfers,
        key_prefix="transfers_tab",
        players=players,
    )

    st.markdown("---")
    # The projection has to be attached here, not just the fixture columns.
    # Without it the replacement ranking silently falls back to fixtures
    # alone, and the whole point is that suggestions are forward-looking.
    projected = cached_scores(players, fixtures, teams, next_event)
    scored = transfers.squad_with_scores(players, fixtures, teams, next_event, FIXTURE_WINDOW)
    projection_columns = [
        c for c in ("xp_horizon", "xp_next", "xp_captain", "expected_minutes", "p_start")
        if c in projected.columns
    ]
    # reset_index first: these frames are indexed by id *and* carry an id
    # column, which makes merging on the name ambiguous and raises.
    scored = scored.reset_index(drop=True).merge(
        projected.reset_index(drop=True)[["id"] + projection_columns],
        on="id", how="left", suffixes=("", "_proj"),
    ).set_index("id", drop=False)
    weaknesses = transfers.squad_weaknesses(scored, squad)

    if weaknesses.empty:
        st.success("No obvious weaknesses flagged in your squad this week.")
        return

    st.markdown("**Players worth reviewing**")
    weakness_cards = [
        player_rank_card(i, row, f"£{row['price']:.1f}m", "price", row["reasons_text"], score_color=SCORE_WARN)
        for i, (_, row) in enumerate(weaknesses.iterrows(), start=1)
    ]
    render_html(render_rank_card_list(weakness_cards))

    weak_names = weaknesses["web_name"].tolist()
    chosen = st.selectbox("See replacement options for:", weak_names)
    if chosen:
        player_id = scored[scored["web_name"] == chosen]["id"].iloc[0]
        budget = st.slider("Extra budget available (£m, on top of selling price)", 0.0, 5.0, 0.0, 0.1)
        replacements = transfers.suggest_replacements(scored, squad, player_id, budget)
        if replacements.empty:
            st.caption("No affordable replacements found in that position/budget.")
        else:
            st.caption(
                "Ranked by projected points over the next five gameweeks, not by what they "
                "scored last week. Those disagree exactly when it matters — a defender fresh "
                "off a goal and a clean sheet tops any form table, and is still the wrong buy "
                "if his side face two of the best attacks next."
            )
            replacement_cards = [
                player_rank_card(
                    i, row, f"{row['replacement_score']:.1f}", "pts next 5",
                    f"£{row['price']:.1f}m · "
                    + (f"**+{row['upgrade']:.1f} pts** on {chosen} · " if row.get("upgrade", 0) else "")
                    + f"{row['fixture_run_difficulty']:.1f} avg FDR · form {row['form']:.1f}",
                )
                for i, (_, row) in enumerate(replacements.iterrows(), start=1)
            ]
            render_html(render_rank_card_list(replacement_cards))


def main():
    inject_global_css()
    hero_header()
    with st.spinner("Pulling the latest FPL data…"):
        players, teams, events, fixtures, state = load_core_data()
    next_event = state.planning_event

    st.sidebar.header("Settings")
    team_id_input = st.sidebar.text_input("Your FPL Team ID", value=FPL_TEAM_ID or "")
    team_id = int(team_id_input) if team_id_input.strip().isdigit() else None

    render_rank_strategy_control()

    if not team_id:
        st.sidebar.info(
            "Enter your FPL Team ID to see your squad and personalised transfer suggestions. "
            "Sign in at fantasy.premierleague.com, open Pick Team → Gameweek History, and "
            "check the URL: .../entry/1234567/history — that number is your Team ID."
        )

    squad = None
    tab_names = ["Starting XI", "Captaincy", "Chips", "Fixtures", "Watchlist", "Injuries", "Odds & Expert Take"]
    if team_id:
        # Once there's a squad to work from, the front page is a weekly
        # plan rather than a from-scratch build, and the name should say so.
        tab_names = ["My Plan", "My Squad"] + tab_names[1:] + ["Transfers"]
    # Last, deliberately. It's the page that marks everything the others
    # said, so it belongs at the end of the argument rather than the front.
    tab_names = tab_names + ["Track record"]

    tabs = st.tabs(tab_names)
    tab_map = dict(zip(tab_names, tabs))

    confirmed = None
    if team_id:
        try:
            confirmed = cached_confirmed_squad(team_id, next_event)
        except Exception:
            confirmed = None

    with tab_map[tab_names[0]]:
        if confirmed is not None:
            render_owned_squad_plan(players, fixtures, teams, next_event, confirmed, state)
        else:
            render_starting_xi_tab(players, fixtures, teams, next_event, state)

    if team_id:
        with tab_map["My Squad"]:
            squad = render_squad_tab(players, team_id, next_event, events, fixtures, teams)

    with tab_map["Captaincy"]:
        render_captaincy_tab(players, fixtures, teams, next_event)

    with tab_map["Chips"]:
        render_chips_tab(players, fixtures, teams, next_event)

    with tab_map["Fixtures"]:
        render_fixtures_tab(players, fixtures, teams, next_event)

    with tab_map["Watchlist"]:
        render_watchlist_tab(players)

    with tab_map["Injuries"]:
        owned_ids = squad.player_ids if squad else None
        render_injuries_tab(players, owned_ids)

    with tab_map["Odds & Expert Take"]:
        render_report_tab(players, fixtures, teams, next_event)

    with tab_map["Track record"]:
        render_track_record_tab(players, events)

    if team_id:
        with tab_map["Transfers"]:
            if squad:
                render_transfers_tab(players, fixtures, teams, next_event, squad)
            else:
                st.info("Transfer suggestions need your squad loaded first — see the My Squad tab.")


if __name__ == "__main__":
    main()

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

from fpl_assistant import api, version
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
    dossier,
    freshness,
    history,
    matchups,
    omissions,
    player_case,
    quality_control,
    planner,
    scenarios,
    gameweek_state,
    snapshots,
    search as research_search,
    rationale,
    squad_builder,
    team_brief,
    transfer_budget,
    transfer_case,
    transfers,
)
from fpl_assistant.analysis.season_state import is_preseason
from fpl_assistant.config import FPL_TEAM_ID
from fpl_assistant.dashboard.cards import SCORE_BAD, SCORE_WARN, player_rank_card, render_rank_card_list
from fpl_assistant.dashboard.htmlutil import render_html
from fpl_assistant.dashboard import media
from fpl_assistant.dashboard.media import player_photo_html
from fpl_assistant.dashboard.pitch import render_pitch_html
from fpl_assistant.dashboard.styles import (
    fdr_color, hero_header, inject_global_css, inject_homepage_css, section_header,
)
from fpl_assistant.research import research_log
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
def cached_matchups(gameweek, _version=""):
    """This gameweek's fixture-level commentary, read once per refresh.

    `_version` is part of the cache key on purpose: it carries the
    deployed commit, so a push that changes the research files produces a
    different key and the new data appears without anyone rebooting
    anything. Streamlit's TTL alone would leave up to half an hour of
    stale reading after a deploy.
    """
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
    "neutral": ("➖ No strong view", "Researched, but the projection decides"),
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
        fixtures = cached_matchups(int(gameweek), _build_id())
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


def render_owned_squad_cases(
    scored, confirmed_ids, suggested_ids, fixtures, teams, next_event, report_text
) -> None:
    """Why you own each of the fifteen you actually own.

    Separate from the suggested XI on purpose. The plan above answers
    "what should I do this week"; a manager deciding whether to trust that
    plan needs the other question answered too — "why am I holding these
    players at all" — and that has to cover the squad as it stands,
    including anyone the plan wants to sell. A page that only explains the
    players it likes is arguing, not informing.
    """
    present = [pid for pid in confirmed_ids if pid in set(scored["id"])]
    if not present:
        return

    indexed = scored.set_index("id", drop=False)
    leaving = [pid for pid in present if pid not in suggested_ids]
    keeping = [pid for pid in present if pid in suggested_ids]

    researched = sum(
        1 for pid in present
        if consensus.arguments_for(indexed.loc[pid])
        or consensus.arguments_against(indexed.loc[pid])
    )

    st.divider()
    with st.expander(
        f"🧾 Your current squad, player by player — {researched} of {len(present)} researched",
        expanded=False,
    ):
        st.caption(
            "The fifteen you own right now, whatever the plan above suggests doing with them. "
            "Anyone the plan would sell is listed first, with the case against them, so you can "
            "disagree with the sale rather than just accept it."
        )
        if leaving:
            st.markdown("**The plan would move these on**")
            render_player_cases(
                indexed, leaving, [], fixtures, teams, next_event, report_text
            )
        if keeping:
            st.markdown("**Staying in the squad**")
            render_player_cases(
                indexed, keeping, [], fixtures, teams, next_event, report_text
            )

        missing = [
            str(indexed.loc[pid].get("web_name"))
            for pid in present
            if not consensus.arguments_for(indexed.loc[pid])
            and not consensus.arguments_against(indexed.loc[pid])
        ]
        if missing:
            st.warning(
                "No researched reasoning yet for: "
                + ", ".join(missing)
                + ". Those write-ups fall back on the projection alone — run /refresh to fill them in."
            )


def _build_id() -> str:
    """The deployed commit, used as a cache key component.

    Research lives in the repository, so new research arrives as a new
    commit. Keying the caches on the commit means a deploy invalidates
    exactly the data the deploy changed — which is what "press Reboot"
    was being used for.
    """
    try:
        return version.current().commit
    except Exception:
        return ""


def render_plan_header(gameweek: int, free_transfers: int = 1, bank: float = 0.0,
                       deadline: str = "", transfers_proposed: int = 0,
                       hit: int = 0) -> None:
    """The first thing on the page: whose plan this is, and the shape of it.

    Replaces a block of research diagnostics. Somebody opening this on a
    phone wants to know their gameweek, their transfer and their money —
    not how many sources were attempted. The diagnostics still exist; they
    now live behind Research details, which is where they belong.
    """
    plan = "No transfer recommended"
    if transfers_proposed == 1:
        plan = "1 transfer recommended"
    elif transfers_proposed > 1:
        plan = f"{transfers_proposed} transfers recommended"
    if hit:
        plan += f" · −{hit} hit"

    render_html(
        "<div class='fpl-plan-head'>"
        f"<h2>Your GW{gameweek} plan</h2>"
        f"<p class='fpl-plan-meta'>{free_transfers} free transfer"
        f"{'s' if free_transfers != 1 else ''} · £{bank:.1f}m in the bank</p>"
        f"<p class='fpl-plan-meta'>{plan}</p>"
        + (f"<p class='fpl-plan-meta'>Deadline {deadline}</p>" if deadline else "")
        + "</div>"
    )


def render_research_details(gameweek: int) -> None:
    """Everything technical, one tap away and closed by default."""
    from fpl_assistant.research import corpus as corpus_mod

    store = corpus_mod.load()
    state = None
    try:
        payload = consensus.load_consensus(int(gameweek)) or {}
        state = freshness.from_files(int(gameweek), payload)
    except Exception:
        pass

    label = "Research: current"
    if not len(store):
        label = "Research: not yet collected"
    elif (age := store.age_hours) is not None and age > 24:
        label = f"Research: {age / 24:.0f} days old"
    st.caption(f"{label} · updated {store.collected_at_display}")

    with st.expander("Research details"):
        st.markdown(
            f"- Sources attempted: **{store.sources_checked}**\n"
            f"- Sources readable: **{store.sources_ok}**\n"
            f"- Articles held: **{len(store)}**\n"
            f"- Last collected: **{store.collected_at_display}**"
        )
        if state and state.message:
            st.caption(state.message)
        build = version.current()
        if build.known:
            st.caption(build.display)
        if st.button("Refresh research now", use_container_width=True,
                     help="Reads every source that publishes a feed or sitemap, "
                          "updates the article cache and re-researches your squad. "
                          "Free — public feeds only."):
            run_research_refresh(int(gameweek))


def render_freshness_bar(gameweek: int, deadline: str = "") -> None:
    """The small status line, and the only refresh control anyone needs.

    Deliberately one line and one button. The homepage is three sections
    and this is not a fourth — it is the footer of the first, telling you
    which gameweek the reasoning belongs to and letting you pull the
    newest committed data without leaving the app.
    """
    try:
        payload = consensus.load_consensus(int(gameweek)) or {}
    except Exception:
        payload = {}
    state = freshness.from_files(int(gameweek), payload, deadline)

    left, right = st.columns([3, 1])
    with left:
        build = version.current()
        st.caption(
            f"**Gameweek {gameweek}** · {state.label}"
            + (f" · {build.display}" if build.known else "")
        )
    with right:
        if st.button("↻ Refresh research", use_container_width=True,
                     help="Goes and reads the football news: fetches every source that "
                          "publishes a feed or sitemap, updates the article cache and "
                          "re-researches your squad. Free — public feeds only, no API key."):
            run_research_refresh(int(gameweek))

    if state.message:
        (st.warning if state.stale else st.info)(state.message)

    render_collection_status()


def render_collection_status() -> None:
    """What the research pipeline last actually retrieved.

    On the page rather than buried in a log, because the failure this
    replaces was invisible: the button reported nothing, retrieved
    nothing, and the write-ups looked the same either way.
    """
    try:
        from fpl_assistant.research import corpus as corpus_mod
        store = corpus_mod.load()
    except Exception:
        return

    if not len(store):
        st.error(
            "**RESEARCH COLLECTION FAILURE** — the article cache is empty, so no player "
            "assessment on this page is backed by current reporting. Press *Refresh "
            "research* to collect, or check the Collect research workflow."
        )
        return

    # PART I. ARTICLE COUNT IS NOT THE METRIC. Three thousand articles
    # is irrelevant if today's team news was missed, and printing the
    # number made a bad run look like a good one. What a manager needs to
    # know before a deadline is whether HIS FIFTEEN have been checked.
    coverage = (load_decision().get("status_coverage") or {})
    age = store.age_hours
    stale = age is not None and age > 12

    if coverage:
        grade = coverage.get("deadline_coverage", "THIN")
        line = (
            f"**{coverage.get('status_checked', '0/0')} status checked**  ·  "
            f"{coverage.get('fresh_evidence_72h', '0/0')} with evidence "
            f"under 72h  ·  "
            f"{coverage.get('predicted_xi_checked', '0/0')} found in a "
            f"predicted XI  ·  deadline coverage **{grade}**")
        moved = coverage.get("recent_transfers") or []
        if moved:
            line += f"  ·  recently transferred: {', '.join(moved)}"
        unchecked = coverage.get("not_recently_verified") or []
        if unchecked:
            line += f"  ·  not re-checked: {', '.join(unchecked)}"
        (st.warning if grade == "THIN" or stale else st.caption)(line)
        with st.expander("Technical details"):
            st.caption(
                f"Research cache: {len(store)} articles from "
                f"{store.sources_ok}/{store.sources_checked} sources · "
                f"collected {store.collected_at_display}. Article volume is "
                f"not the target — decision quality and freshness are — so "
                f"the count lives here rather than on the page.")
        return

    line = (f"Research cache: **{len(store)} articles** from "
            f"{store.sources_ok}/{store.sources_checked} sources · "
            f"collected {store.collected_at_display}")
    (st.warning if stale else st.caption)(line + ("  ·  worth refreshing" if stale else ""))


def run_research_refresh(gameweek: int) -> None:
    """The Refresh button's actual work: the five-stage research pipeline.

    This used to be `st.cache_data.clear()`. Clearing a cache re-reads the
    same files; it cannot discover that a manager named a squad. The button
    now runs the same pipeline the scheduled workflow runs — discover,
    filter, dedupe, rank, deep-read — so pressing it genuinely researches.

    The mode is chosen rather than fixed: a new gameweek needs the full
    three-week picture, a deadline needs the last 72 hours of team news,
    and the rest of the time only what is new since the last run.
    """
    import json as _json
    from datetime import datetime, timezone
    from pathlib import Path as _Path

    from fpl_assistant.research import collect, corpus as corpus_mod, pipeline

    root = _Path(__file__).resolve().parent.parent.parent
    try:
        discovery = _json.loads((root / "data" / "sources" / "discovery.json").read_text())
    except (OSError, ValueError):
        st.error("**RESEARCH COLLECTION FAILURE** — no source discovery audit found. "
                 "Run the Collect research workflow with mode `probe` first.")
        return

    sources = [s for s in discovery.get("sources", [])
               if s.get("grade") in collect.USABLE_GRADES and s.get("feed_url")]
    if not sources:
        st.error("**RESEARCH COLLECTION FAILURE** — no source exposes a feed or sitemap "
                 "the app can read.")
        return

    squad = my_squad_players()
    store = corpus_mod.load()

    # A stale or empty cache needs the full picture; otherwise only what
    # has appeared since. Inside a deadline window the pass narrows onto
    # team news, because that is the only thing that still changes.
    mode = pipeline.FULL
    since = None
    if len(store) and store.collected_at:
        mode = pipeline.INCREMENTAL
        since = datetime.fromisoformat(store.collected_at)
    if _within_deadline_window(gameweek):
        mode, since = pipeline.DEADLINE, None

    bar = st.progress(0.0, text="Starting the research pass…")
    articles, report = pipeline.run(
        sources, squad, int(gameweek), mode=mode, since=since, known=store.items,
        progress=lambda fraction, text: bar.progress(min(fraction, 1.0), text=text))

    store = corpus_mod.prune(corpus_mod.merge(store, articles))
    store.collected_at = report.ran_at
    store.sources_checked = report.sources_attempted
    store.sources_ok = report.sources_readable
    store.failures = report.failures[:40]
    corpus_mod.save(store)
    report.corpus_size = len(store)
    report.verdicts = pipeline.verdicts(report, len(store))

    # Stage B, immediately. Refreshing the corpus without regenerating the
    # prose would leave the page showing yesterday's write-ups over
    # today's evidence, which is the same class of lie as not refreshing
    # at all — worse, because the timestamp would say it was current.
    bar.progress(0.97, text="Writing up every player from the new evidence…")
    from fpl_assistant.analysis import writeup as writeup_mod
    writeups = writeup_mod.build_all(
        squad,
        {name: pipeline._as_player_evidence(rec, len(store))
         for name, rec in report.players.items()},
        starting_ids={p["id"] for p in squad if not p.get("on_bench")},
        captain_id=next((p["id"] for p in squad if p.get("is_captain")), None),
    )
    try:
        (root / "data" / "research" / "writeups.json").write_text(_json.dumps({
            "note": "Homepage prose composed from data/research/corpus.json.",
            "generated": report.ran_at, "gameweek": int(gameweek),
            "corpus_size": len(store),
            "players": {n: w.as_dict() for n, w in writeups.items()},
        }, indent=1, ensure_ascii=False) + "\n")
    except OSError:
        st.warning("The corpus refreshed but the write-ups could not be saved to disk "
                   "(read-only filesystem). The page will show the previous prose.")
    bar.empty()

    # PART N. One coherent pipeline. Refreshing the corpus and stopping
    # there leaves the page showing yesterday's status over today's
    # evidence — the same class of lie as not refreshing at all, and
    # worse, because the timestamp would say it was current. So the
    # status pass, the transfer plan, the write-ups and the question
    # engine's state are all regenerated from the corpus that was just
    # collected, in that order, because each depends on the last.
    bar = st.progress(0.98, text="Re-checking every player's current status…")
    rebuilt = _rebuild_decision()
    bar.empty()

    report.writeups_with_prose = sum(1 for w in writeups.values() if w.has_prose)
    render_research_summary(report, store)
    if rebuilt:
        st.success(rebuilt)
    st.cache_data.clear()


def _rebuild_decision() -> str:
    """Re-runs the decision pipeline against the corpus just collected.

    Invoked in-process rather than shelled out, so a read-only filesystem
    or a missing FPL connection degrades to a message instead of a
    traceback. The heavy lifting is the same module the scheduled
    workflow runs — there is one pipeline, not an app copy of it.
    """
    import subprocess
    import sys as _sys
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parent.parent.parent
    script = root / "scripts" / "decide_transfers.py"
    if not script.exists():
        return ""
    try:
        finished = subprocess.run(
            [_sys.executable, str(script)], cwd=str(root),
            capture_output=True, text=True, timeout=600)
    except Exception as exc:
        return f"Status pass could not be re-run here ({exc.__class__.__name__})."
    if finished.returncode != 0:
        tail = (finished.stdout or finished.stderr or "").strip().splitlines()
        return ("Status re-checked, but the completeness gate did not pass: "
                + (tail[-1] if tail else "no detail"))
    return ("Status, transfer plan, write-ups and the question box have all "
            "been rebuilt from the evidence just collected.")


def _within_deadline_window(gameweek: int, hours: int = 48) -> bool:
    """Is the next deadline close enough to narrow the search?"""
    try:
        from fpl_assistant import api
        from fpl_assistant.models import events_df
        events = events_df(api.get_bootstrap_static())
        row = events[events["id"] == int(gameweek)]
        if row.empty:
            return False
        deadline = pd.to_datetime(row.iloc[0]["deadline_time"], utc=True)
        delta = (deadline - pd.Timestamp.now(tz="UTC")).total_seconds() / 3600
        return 0 <= delta <= hours
    except Exception:
        return False


def render_research_summary(report, store) -> None:
    """The numbers, exactly as specified, and no padding of them.

    `candidates discovered` and `substantive items` are deliberately shown
    side by side. The gap between them is the junk this pipeline throws
    away, and hiding it would let the headline number drift back toward
    counting tool pages — the failure that produced a fake 15/15.
    """
    st.markdown(
        f"**SOURCES ATTEMPTED:** {report.sources_attempted}  ·  "
        f"**READABLE:** {report.sources_readable}  \n"
        f"**CANDIDATE ITEMS DISCOVERED:** {report.candidates_discovered}  ·  "
        f"**SUBSTANTIVE:** {report.substantive_items}  \n"
        f"**DUPLICATES REMOVED:** {report.duplicates_removed}  ·  "
        f"**DEEPLY ANALYSED:** {report.deeply_analysed}  \n"
        f"**PLAYERS FULLY RESEARCHED:** {report.players_researched}/{len(report.players)}  \n"
        f"**LAST UPDATED:** {store.collected_at_display}  ·  {report.mode} pass, "
        f"{report.seconds:.0f}s"
    )
    for verdict in report.verdicts.values():
        if not verdict["ok"]:
            st.error(f"**{verdict['headline']}** — " + " · ".join(verdict["reasons"]))

    short = [name for name, rec in report.players.items() if not rec.researched]
    if short:
        st.warning(
            "Below the three-item evidence threshold after every avenue was tried: "
            + ", ".join(short)
            + ". Their write-ups say so rather than inventing a view."
        )


def my_squad_players() -> list[dict]:
    """The owned fifteen, as plain dicts, from the committed squad file."""
    import json as _json
    from pathlib import Path as _Path

    path = _Path(__file__).resolve().parent.parent.parent / "data" / "squad" / "current.json"
    try:
        return _json.loads(path.read_text()).get("squad", [])
    except (OSError, ValueError):
        return []


def _section(title: str, subtitle: str = "") -> None:
    render_html(f"<div class='fpl-section'>{title}</div>")
    if subtitle:
        render_html(f"<p class='fpl-sub'>{subtitle}</p>")


@st.cache_data(ttl=120)
def load_decision() -> dict:
    """The transfer decision, built from the squad rather than a shopping list."""
    import json as _json
    from pathlib import Path as _Path
    path = (_Path(__file__).resolve().parent.parent.parent
            / "data" / "research" / "decision.json")
    try:
        return _json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def render_transfer_decision() -> None:
    """One decision, with the argument for it one tap away.

    The collapsed card carries the four numbers a manager checks before
    anything else — free transfers, hit, net effect, confidence — and the
    reasoning opens underneath. Everything technical is nested a level
    deeper, on the same principle as the player rows: the judgement
    first, the evidence available but never in front of it.
    """
    payload = load_decision()
    rec = payload.get("recommendation") or {}
    brief = payload.get("transfer_brief") or {}
    explanation = payload.get("explanation") or {}
    if not rec and not brief:
        return

    _section("Transfer plan")

    if rec.get("incomplete"):
        render_html(
            "<div class='fpl-card fpl-plan-card'>"
            "<h3>No recommendation this week</h3>"
            "<p class='fpl-meta'>Required data is missing</p></div>")
        st.markdown("**Why.** " + explanation.get("problem", ""))
        return

    plan = rec.get("winner") or {}
    acting = bool(plan.get("moves"))
    headline = brief.get("label") or ("Roll the transfer" if not acting
                                      else plan.get("label", ""))

    if acting:
        rows = "".join(
            "<div class='fpl-swap'>"
            f"<div class='fpl-out'><div class='lab'>Out</div>"
            f"<div class='leg'>{m['out']}</div></div>"
            "<div class='arrow'>↓</div>"
            f"<div class='fpl-in'><div class='lab'>In</div>"
            f"<div class='leg'>{m['in']}</div></div></div>"
            for m in plan.get("moves", []))
    else:
        rows = "<p class='fpl-meta'>Keep the transfer — it becomes two next week</p>"

    hit = plan.get("hit", 0)
    tags = "".join((
        _tag("t-flat", f"FT {plan.get('free_transfers', 1)}"),
        _tag("t-bad" if hit else "t-good",
             f"Hit −{hit:.0f}" if hit else "No hit"),
        _tag("t-good" if plan.get("net_5gw", 0) > 0 else "t-warn",
             f"Net 5-GW {plan.get('net_5gw', 0):+.1f}"),
        _tag(CONFIDENCE_TAGS.get(brief.get("confidence", ""), "t-flat"),
             f"{brief.get('confidence', 'Medium')} confidence"),
    ))
    render_html(f"<div class='fpl-card fpl-plan-card'><h3>{headline}</h3>"
                f"{rows}<div class='tags'>{tags}</div></div>")

    if brief.get("verdict_label"):
        render_html(
            f"<div class='fpl-verdict'>"
            f"<div class='label'>{brief['verdict_label']}</div>"
            f"{brief.get('verdict', '')}</div>")

    with st.expander("Why this transfer?"):
        if brief.get("arithmetic"):
            st.caption(brief["arithmetic"])
        for heading, key in (("Why this move", "why_move"),
                             ("The case for", "case_for"),
                             ("The case against", "case_against"),
                             ("Why this player out", "why_out"),
                             ("Why this player in", "why_in"),
                             ("Why now", "why_now"),
                             ("Why not roll", "why_not_roll"),
                             ("3-5 gameweek plan", "horizon")):
            if brief.get(key):
                st.markdown(f"**{heading}.** {brief[key]}")

    with st.expander("Deeper evidence & sources"):
        st.caption("Every item here was graded for this decision before any "
                   "of it was believed.")
        items = brief.get("evidence") or []
        for item in items[:8]:
            st.markdown(
                f"- **{item.get('about', '')}** · {item.get('kind', '')}"
                f" · {item.get('source', 'unknown')} — {item.get('text', '')}")
        if not items:
            st.markdown("Nothing published this week argues for or against "
                        "this decision; it rests on the official data, the "
                        "fixtures and the checked minutes.")
        failed = [row for row in (brief.get("trust") or []) if not row["passed"]]
        st.markdown("**Trust test.** "
                    + ("All ten questions pass." if not failed else
                       "Failed: " + "; ".join(row["question"] for row in failed)))

    alternatives = payload.get("transfer_alternatives") or []
    if alternatives:
        with st.expander(f"Alternatives considered ({len(alternatives)})"):
            for other in alternatives:
                st.markdown(f"**{other['label']}** — {other['note']}")
                inner = other.get("brief") or {}
                if inner.get("why_move"):
                    with st.expander("More"):
                        for heading, key in (("Why this move", "why_move"),
                                             ("The case against", "case_against"),
                                             ("Verdict", "verdict")):
                            if inner.get(key):
                                st.markdown(f"**{heading}.** {inner[key]}")

    refused = payload.get("transfer_rejected") or []
    if refused:
        with st.expander(f"Ruled out ({len(refused)})"):
            st.caption("These failed one of the twelve checks, so they are "
                       "not options with a caveat — they are out.")
            for other in refused:
                st.markdown(f"**{other['label']}** — {other['note']}")

    watchlist = payload.get("transfer_watchlist") or []
    if watchlist:
        with st.expander("Watchlist — what would change this"):
            for entry in watchlist:
                st.markdown(f"**{entry['label']}**  \n{entry['note']}")

    ranking = payload.get("sell_urgency_ranking") or []
    if ranking:
        with st.expander("How every player was rated"):
            st.caption("Scored from this week's evidence and the official "
                       "data. No player is protected by name.")
            for row in ranking:
                st.markdown(f"**{row['player']}** — {row['band']}"
                            + (f" · {row['reasons'][0]}" if row.get("reasons")
                               else ""))


def render_sell_urgency() -> None:
    """The diagnosis the whole decision rests on, shown rather than hidden.

    It goes on the page because the reader's first question about any
    suggested transfer is "why him?", and the answer is a ranking — not a
    sentence about the one player being sold.
    """
    payload = load_decision()
    ranking = payload.get("sell_urgency_ranking") or []
    if not ranking:
        return
    with st.expander("Sell urgency — all 15, most sellable first"):
        st.caption(
            "Scored 0–100 from this week's evidence and the official FPL data. "
            "No player is protected by name: a premium survives because his "
            "evidence protects him, and the engine will sell anyone whose "
            "situation deteriorates."
        )
        for index, row in enumerate(ranking, 1):
            reasons = "; ".join(row.get("reasons", [])[:2])
            protections = "; ".join(row.get("protections", [])[:1])
            st.markdown(
                f"**{index}. {row['player']}** ({row['position']}, £{row['price']:.1f}m) "
                f"— **{row['sell_urgency']:.0f}/100**, {row['band']} "
                f"· hold strength {row['hold_strength']:.0f}"
                + (f"  \n  ↳ {reasons}" if reasons else "")
                + (f"  \n  ↳ protected by {protections}" if protections else "")
            )


def render_corpus_transfer(out_name: str, in_name: str) -> bool:
    """The four questions a transfer has to answer, argued from evidence."""
    from fpl_assistant.analysis import writeup as writeup_mod

    payload = load_writeups()
    players = payload.get("players") or {}
    if out_name not in players or in_name not in players:
        return False

    def revive(entry):
        made = writeup_mod.PlayerWriteup(
            player=entry["player"], club=entry.get("club", ""),
            case_for=entry.get("case_for", ""), case_against=entry.get("case_against", ""),
            expected_minutes=entry.get("expected_minutes", ""),
            evidence_used=entry.get("evidence_used", []),
        )
        made.quotes = [writeup_mod.Quote(**{k: v for k, v in q.items() if k != "topics"})
                       for q in (entry.get("quotes") or [])]
        return made

    case = writeup_mod.transfer(revive(players[out_name]), revive(players[in_name]))
    for heading, body in (("Why this player out", case.why_out),
                          ("Why this player in", case.why_in),
                          ("Why not the obvious alternative", case.why_not_alternative),
                          ("What it means for the next few gameweeks",
                           case.next_few_gameweeks)):
        if body:
            st.markdown(f"**{heading}.** {body}")
    st.caption(f"Argued from the research corpus. Confidence: {case.confidence}.")
    return True


def render_transfer_block(case, index: int) -> None:
    """One suggested transfer, argued rather than announced.

    Laid out vertically — SELL, arrow, BUY — because that is the shape
    that survives a phone screen. A side-by-side comparison table is the
    first thing that breaks at 390px wide, and it was never clearer than
    the arrow anyway.
    """
    confidence = case.confidence
    pill = {"High": "fpl-high", "Medium": "fpl-med", "Low": "fpl-low"}[confidence]

    render_html(
        "<div class='fpl-card'>"
        "<div class='fpl-swap'>"
        f"<div class='fpl-out'><div class='lab'>Sell</div>"
        f"<div class='leg'>{case.out.name}</div>"
        f"<div class='fpl-meta'>{case.out.team} · {case.out.position} · £{case.out.price:.1f}m</div></div>"
        "<div class='arrow'>↓</div>"
        f"<div class='fpl-in'><div class='lab'>Buy</div>"
        f"<div class='leg'>{case.into.name}</div>"
        f"<div class='fpl-meta'>{case.into.team} · {case.into.position} · £{case.into.price:.1f}m</div></div>"
        "</div>"
        f"<div style='text-align:center'><span class='fpl-pill {pill}'>Confidence: {confidence}</span></div>"
        "</div>"
    )

    st.markdown("**Why this transfer?**")

    # The corpus argues the move first, because it is reporting. What
    # follows is the structured case built from projections and fixture
    # data, which is computation and belongs second.
    argued = render_corpus_transfer(case.out.name, case.into.name)

    if not argued:
        st.markdown(f"**Selling {case.out.name}.** " + (
            " ".join(f"{point} ({source})." for point, source in case.out.reasons)
            or "Nothing specific is being said against him — he is simply the player the squad can most afford to lose."
        ))
        st.markdown(f"**Buying {case.into.name}.** " + (
            " ".join(f"{point} ({source})." for point, source in case.into.reasons)
            or "No researched case beyond the projection, which is thin ground for spending a transfer."
        ))
    if case.into.record:
        st.markdown(f"**His record against them.** {case.into.record}")
    st.markdown(case.why_this_swap)
    why_him = getattr(case, "why_not_instead", "")
    if why_him:
        st.markdown(f"**Why sell {case.out.name} rather than someone else?** {why_him}")

    st.markdown(f"**Short-term.** {case.short_term}")
    st.markdown(f"**Next {transfer_case.LOOKAHEAD_GAMEWEEKS} gameweeks.** {case.look_ahead}")
    if case.alternative:
        st.markdown(f"**Alternative.** {case.alternative}")
    st.markdown(f"**Roll the transfer?** {case.roll_verdict}")

    everyone = case.out.reasons + case.into.reasons
    named = list(dict.fromkeys(source for _, source in everyone if source))
    if named:
        with st.expander(f"Sources used: {len(named)}"):
            for source in named:
                st.markdown(f"- {source}")
    st.markdown("---")


VERDICT_STYLE = {
    "KEEP": ("fpl-high", "Keep"),
    "CAPTAIN": ("fpl-high", "Captain"),
    "VICE-CAPTAIN": ("fpl-high", "Vice-captain"),
    "BENCH": ("fpl-med", "Bench"),
    "MONITOR": ("fpl-med", "Monitor"),
    "SELL": ("fpl-low", "Sell"),
}


@st.cache_data(ttl=120)
def load_writeups() -> dict:
    """Homepage prose, composed from the research corpus.

    Cached briefly rather than not at all: it is read once per player card
    and the file only changes when a refresh runs.
    """
    import json as _json
    from pathlib import Path as _Path
    path = (_Path(__file__).resolve().parent.parent.parent
            / "data" / "research" / "writeups.json")
    try:
        return _json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


# The three things a manager checks on a phone before a deadline, and
# the colour each of them earns. Nothing else in a player row is tinted.
OUTLOOK_TAGS = {
    "Very likely to start": ("t-good", "STARTS"),
    "Likely to start": ("t-good", "LIKELY"),
    "50-50": ("t-warn", "50-50"),
    "Likely bench": ("t-warn", "BENCH"),
    "Very unlikely to start": ("t-bad", "UNLIKELY"),
    "Out": ("t-bad", "OUT"),
}
CONFIDENCE_TAGS = {"High": "t-good", "Medium": "t-warn", "Low": "t-bad"}
VERDICT_TAGS = {
    "CAPTAIN": "t-accent", "VICE-CAPTAIN, AND HOLD": "t-accent",
    "START AND HOLD": "t-good", "KEEP THROUGH THE TOUGH FIXTURE": "t-good",
    "START, BUT MONITOR": "t-warn", "HOLD THIS WEEK, REASSESS NEXT": "t-warn",
    "BENCH AND HOLD": "t-flat", "BENCH, AND MONITOR": "t-warn",
    "SELL": "t-bad", "SELL IF THE MINUTES CONCERN IS CONFIRMED": "t-bad",
}


def _tag(css_class: str, text: str) -> str:
    return f"<span class='fpl-tag {css_class}'>{text}</span>"


def render_ask_box() -> None:
    """A direct question, answered from the state the page is showing.

    Deliberately at the bottom: the page should have answered most of it
    already, and this is for the thing it did not. The answer is read off
    the same committed decision the rows above render, so it cannot tell
    a manager something the card underneath it contradicts.
    """
    from fpl_assistant.analysis import squad_questions

    _section("Ask about my team", "Answered from this week's checked status.")
    decision = load_decision()
    if not decision:
        st.info("No decision file has been generated yet. Run Refresh "
                "Research and the question box will have something to read.")
        return

    st.caption("Try: " + " · ".join(squad_questions.SUGGESTIONS[:4]))
    question = st.text_input(
        "Ask about your FPL team…", key="ask_about_my_team",
        placeholder="Ask about your FPL team…", label_visibility="collapsed")
    if not question:
        return

    answer = squad_questions.answer(question, decision)
    render_html(
        f"<div class='fpl-ask-answer'><h5>{answer.headline}</h5>"
        f"<p><b>{answer.short_answer}</b></p></div>")
    if answer.why:
        st.markdown(f"**Why.** {answer.why}")
    facts = []
    if answer.call:
        facts.append(f"**My call.** {answer.call}")
    if answer.expected_minutes:
        facts.append(f"**Expected minutes.** {answer.expected_minutes}")
    if answer.confidence:
        facts.append(f"**Confidence.** {answer.confidence}")
    if facts:
        st.markdown("  \n".join(facts))
    if answer.caveat:
        st.caption(answer.caveat)
    if answer.evidence:
        with st.expander(f"Evidence used ({len(answer.evidence)})"):
            for item in answer.evidence[:6]:
                st.markdown(
                    f"- **{item.get('source', 'unknown')}** · "
                    f"{item.get('kind', '')} · {item.get('when', '')} — "
                    f"{item.get('title', '')}")
                if item.get("url"):
                    st.caption(item["url"])


def render_armband_case(player_cases) -> None:
    """The captaincy argued once, under the team, rather than per player.

    It used to live inside a per-player card. With one component per
    player and everything collapsed, the biggest free decision of the
    week would have spent the season behind a tap — so it moves out to
    where the eleven is chosen, which is where a manager is looking when
    he makes it.
    """
    captain = next((case for case in player_cases if case.captain), None)
    vice = next((case for case in player_cases if case.vice_captain), None)
    if not captain and not vice:
        return

    for case, alternative, which in ((captain, vice, "Captaincy"),
                                     (vice, captain, "Vice-captaincy")):
        if case is None:
            continue
        parts = [f"**{which} reasoning.** {case.name}."]
        if case.case_for:
            parts.append(case.case_for[0][0].rstrip(".")
                         + f" ({case.case_for[0][1]}).")
        if case.record_vs:
            parts.append(f"Against this opponent: {case.record_vs}")
        if case.ownership >= 40:
            parts.append(
                f"At {case.ownership:.0f}% owned this is the safe armband "
                f"rather than the clever one — it protects rank more than it "
                f"gains it.")
        else:
            parts.append(
                f"At {case.ownership:.0f}% owned this is a genuine "
                f"differential armband. Take it deliberately rather than by "
                f"accident.")
        if alternative is not None:
            parts.append(f"The alternative is {alternative.name}.")
        st.markdown(" ".join(parts))


def player_row_html(facts: dict, status: dict, photo: str) -> str:
    """One player, collapsed: the whole decision on a single line of card.

    Fifteen of these ARE the squad section, so the row has to answer
    three questions without being opened — what the plan says, whether he
    is going to be on the pitch, and how sure that is. Everything else
    waits behind the tap.
    """
    brief = facts.get("brief") or {}
    label = brief.get("verdict_label", "")
    outlook = status.get("outlook", "")
    outlook_class, outlook_text = OUTLOOK_TAGS.get(outlook, ("t-flat", "UNCHECKED"))
    confidence = brief.get("confidence") or status.get("confidence", "")

    tags = []
    if label:
        tags.append(_tag(VERDICT_TAGS.get(label, "t-flat"), label))
    tags.append(_tag(outlook_class, outlook_text))
    if confidence:
        tags.append(_tag(CONFIDENCE_TAGS.get(confidence, "t-flat"),
                         f"{confidence} confidence"))

    fixtures = brief.get("next_four") or facts.get("next_fixtures") or []
    next_up = fixtures[0] if fixtures else ""
    minutes = status.get("minutes_label", "")

    return (
        "<div class='fpl-prow'>"
        f"<span class='face'>{photo}</span>"
        "<span class='body'>"
        f"<div class='name'>{facts['player']}</div>"
        f"<div class='sub'>{facts['club']} · {facts['position']} · "
        f"£{facts['price']:.1f}m{(' · ' + minutes) if minutes else ''}</div>"
        f"<div class='tags'>{''.join(tags)}</div>"
        "</span>"
        f"<span class='fx'><b>{next_up}</b>next</span>"
        "</div>")


def render_player(facts: dict, status: dict, photo: str) -> None:
    """One player = one top-level dropdown, closed until asked for.

    The judgement opens first and everything technical is nested one
    level deeper, because the reader's question is "what do I do with
    him", not "what did you read". Evidence is inspectable, and it is
    inspectable LAST.
    """
    brief = facts.get("brief") or {}
    header = (f"{facts['player']} · {brief.get('verdict_label', 'REVIEW')}"
              f" · {status.get('outlook', 'unchecked')}")

    with st.expander(header):
        render_html(player_row_html(facts, status, photo))

        if brief.get("why"):
            render_html(f"<div class='fpl-lead'>{brief['why']}</div>")

        label = brief.get("verdict_label", "")
        if label:
            render_html(
                f"<div class='fpl-verdict'><div class='label'>{label}</div>"
                f"{brief.get('verdict', '')}</div>")

        with st.expander("This gameweek"):
            st.markdown(brief.get("case_for")
                        or "No fixture reading was generated for him.")
            if facts.get("fixture"):
                st.caption(facts["fixture"])

        with st.expander("Role & minutes"):
            _render_role_and_minutes(status, facts)

        with st.expander("Next 4 gameweeks"):
            runs = brief.get("next_four") or facts.get("next_fixtures") or []
            if runs:
                render_html("<div class='fpl-run'>"
                            + "".join(f"<span>{fx}</span>" for fx in runs[:4])
                            + "</div>")
            st.markdown(brief.get("verdict")
                        or "No forward view was generated for him.")

        with st.expander("The case against"):
            st.markdown(brief.get("against")
                        or "No specific doubt was recorded, which is thinner "
                           "comfort than it sounds.")

        with st.expander("Evidence & sources"):
            _render_evidence(status, facts)


def _render_role_and_minutes(status: dict, facts: dict) -> None:
    """Everything that bears on whether he is on the pitch, with its date."""
    if not status:
        st.markdown("No current status has been recorded for him.")
        return
    lines = [
        f"**Starting outlook.** {status.get('outlook', 'unchecked')}",
        f"**Expected minutes.** {status.get('minutes_label', 'unknown')}",
        f"**Recent starts.** {status.get('starts', 0)} of "
        f"{status.get('team_games', 0)} this season"
        + (f", {status.get('prior_minutes', 0):,} minutes at the club last year"
           if status.get("prior_minutes") else ""),
    ]
    if status.get("new_club"):
        lines.append(f"**New club.** {status['new_club']}")
    if status.get("role"):
        lines.append(f"**Role.** {status['role']}")
    pieces = []
    if status.get("penalties"):
        pieces.append("penalties")
    if status.get("set_pieces"):
        pieces.append("set pieces")
    if pieces:
        lines.append(f"**Set pieces.** He takes the {' and '.join(pieces)}.")
    if status.get("injury"):
        lines.append(f"**Injury.** {status['injury']}")
    if status.get("suspension"):
        lines.append(f"**Suspension.** {status['suspension']}")
    if status.get("manager_quote"):
        lines.append(f"**The manager said.** “{status['manager_quote']}”")
    st.markdown("  \n".join(lines))

    tally = status.get("lineups") or {}
    st.markdown("**Latest status evidence.** " + (
        tally.get("summary") or "no current predicted line-up names him"))
    st.caption(
        f"Resting on {status.get('basis', 'the appearance record')}"
        + (" · not re-checked recently" if status.get("stale") else "")
        + f" · {status.get('fresh_source_count', 0)} source(s) in the last "
          f"72 hours")
    for reason in (status.get("vetoes") or [])[:2]:
        st.warning(reason)


def _render_evidence(status: dict, facts: dict) -> None:
    """The raw material, graded, and kept away from the judgement."""
    st.caption("What the judgement above was built from. Graded for THIS "
               "question — a predicted line-up published today outranks a "
               "month-old piece calling him nailed.")
    items = (status or {}).get("evidence") or []
    for item in items[:6]:
        st.markdown(
            f"- **{item.get('source', 'unknown')}** · {item.get('kind', '')}"
            f" · {item.get('when', '')} · tier {item.get('tier', '?')}"
            f" ({item.get('tier_name', '')}) — {item.get('title', '')}")
        if item.get("url"):
            st.caption(item["url"])
    if not items:
        st.markdown("No article retrieved this week addresses his selection, "
                    "so the judgement rests on the official appearance "
                    "record, the fixtures and the fixture difficulty.")
    for label, key in (("Availability", "availability"),
                       ("Recent selection", "recent_selection"),
                       ("Form", "form"), ("Underlying data", "underlying"),
                       ("Expert view", "expert_view")):
        if facts.get(key):
            st.markdown(f"**{label}.** {facts[key]}")


def render_corpus_writeup(name: str) -> bool:
    """The player's write-up, every sentence quoted from a real article.

    Returns whether anything was rendered, so the caller can tell the
    difference between "the corpus had nothing" and "the corpus was never
    consulted" — a distinction this app spent a long time unable to make.
    """
    payload = load_writeups()
    entry = (payload.get("players") or {}).get(name)
    if not entry:
        return False

    sections = (
        ("Current status", entry.get("status")),
        ("Why he is here", entry.get("why_here")),
        ("Case for keeping", entry.get("case_for")),
        ("Case for selling", entry.get("case_against")),
        ("Expected minutes", entry.get("expected_minutes")),
        ("Recent developments", entry.get("developments")),
        ("Next 3–5 gameweeks", entry.get("outlook")),
    )
    rendered = False
    for heading, body in sections:
        if not body:
            continue
        rendered = True
        st.markdown(f"**{heading}.** {body}")

    used = entry.get("evidence_used") or []
    sources = entry.get("sources_used") or []
    if used:
        st.caption(
            f"Composed from {entry.get('evidence_count', len(used))} retrieved item(s) "
            f"across {len(sources)} source(s) — {', '.join(sources[:6])}. "
            f"Confidence: {entry.get('confidence', 'low')}."
        )
        with st.expander(f"Evidence behind this write-up ({len(used)} links)"):
            for quote in (entry.get("quotes") or [])[:8]:
                st.markdown(f"- *{quote['source']}* — “{quote['text']}”  \n  {quote['url']}")
            for url in used:
                st.caption(url)
    return rendered


def render_owned_squad_plan(players, fixtures, teams, next_event, confirmed, state) -> None:
    """The homepage: squad, transfers, and why every player is here.

    Three sections and nothing else. Everything that used to sit on this
    page — coverage meters, factor panels, omissions, the multi-week
    planner, the question box — is still in the app, on its own tab. It was
    all competing with the two things somebody actually opens this for
    before a deadline: who plays, and what should I change.
    """
    inject_homepage_css()
    render_html("<div class='fpl-home'>")

    squad = confirmed.squad
    scored = cached_scores(players, fixtures, teams, next_event)
    owned_ids = [p.player_id for p in squad.picks]
    confirmed_ids = list(owned_ids)
    owned = scored[scored["id"].isin(owned_ids)].copy()
    fixture_table = fixtures_analysis.team_fixture_table(
        fixtures, teams, next_event, transfer_case.LOOKAHEAD_GAMEWEEKS
    )

    if state is not None:
        render_live_gameweek_notice(state, scored)

    render_freshness_bar(next_event)

    free_transfers = cached_free_transfers(squad.team_id)
    bank = float(squad.bank or 0.0)

    # --- rank the squad by sell urgency BEFORE choosing a replacement ---
    #
    # The old order was backwards: find an attractive target, then look for
    # whoever the money worked against. That is how a settled starter gets
    # sold to fund another midfielder while a player in the middle of a
    # transfer saga is kept.
    matchup_fixtures = cached_matchups(int(next_event), _build_id())
    squad_dossiers = []
    for pid in owned_ids:
        if pid not in scored.index and pid not in set(scored["id"]):
            continue
        row = scored[scored["id"] == pid]
        if row.empty:
            continue
        row = row.iloc[0].copy()
        run, _ = transfer_case._fixture_run(
            row, fixture_table, next_event, transfer_case.LOOKAHEAD_GAMEWEEKS
        )
        squad_dossiers.append(dossier.build(
            row, next_event, fixtures=matchup_fixtures, fixture_run=run, starting=True,
        ))
    ranking = dossier.rank_by_sell_urgency(squad_dossiers)

    # --- the transfer decision -----------------------------------------
    #
    # THERE IS ONE ENGINE. This page used to run two: the PuLP optimiser
    # below chose transfers for the suggested eleven at the top, and the
    # plan engine chose a different answer for the section underneath. So
    # the page could show a squad with a transfer already applied while
    # the next heading said "roll", and each half could cite reasoning
    # that contradicted the other. That is not a rendering bug to patch —
    # it is two opinions printed as one recommendation.
    #
    # The optimiser still runs, because its budget advice is used
    # elsewhere, but it no longer decides anything the reader sees. The
    # squad shown, the transfers named and every player's card all come
    # off the same committed decision.
    try:
        budget = transfer_budget.decide(owned, free_transfers=free_transfers)
    except Exception:
        budget = None

    decision_payload = load_decision()
    recommendation = decision_payload.get("recommendation") or {}
    winning_plan = recommendation.get("winner") or {}
    by_web_name = {}
    for _, row in scored.iterrows():
        by_web_name.setdefault(str(row.get("web_name")), int(row["id"]))

    apply_ids, incoming_ids = set(), []
    for move in winning_plan.get("moves", []):
        out_id = by_web_name.get(move.get("out"))
        in_id = by_web_name.get(move.get("in"))
        # Both halves must resolve, or the swap is not applied at all: a
        # squad missing a player it sold is worse than one showing the
        # move undone.
        if out_id in owned_ids and in_id is not None:
            apply_ids.add(out_id)
            incoming_ids.append(in_id)

    suggested_ids = [i for i in owned_ids if i not in apply_ids] + incoming_ids
    suggested = scored[scored["id"].isin(suggested_ids)].copy()
    if len(suggested) < 15:
        suggested, suggested_ids = owned, list(owned_ids)

    decision_file = load_decision()
    all_facts = decision_file.get("player_facts") or {}
    all_status = decision_file.get("player_status") or {}

    # ================= SECTION 1 — THIS WEEK'S SUGGESTED TEAM ==========
    _section(
        f"This week's suggested team",
        f"Gameweek {next_event} · built from the squad you confirmed in GW{confirmed.event}",
    )

    # PART M. A projection is what a player scores IF HE PLAYS. Picking
    # an eleven on that alone starts a high-ceiling player with a
    # one-in-four chance of being on the pitch ahead of a reliable one —
    # a trade nobody would make if it were stated out loud. Multiplying
    # by the checked start probability states it.
    shares = {}
    for name, state in all_status.items():
        share = state.get("expected_share")
        if share is not None:
            shares[name] = float(share)
    suggested = suggested.copy()
    suggested["expected_share"] = [
        shares.get(str(row), 1.0) for row in suggested["web_name"]]
    suggested["xp_with_minutes"] = (
        suggested["xp_next"].fillna(0) * suggested["expected_share"])

    starting, bench, formation = [], [], None
    captain_id = vice_id = None
    try:
        starting, bench, formation = optimiser.optimise_starting_xi(
            suggested, points_column="xp_with_minutes")
        captain_id, vice_id = squad_builder.pick_captain(suggested, starting)
    except Exception:
        available = suggested.sort_values("xp_next", ascending=False)
        starting = available["id"].head(11).tolist()
        bench = available["id"].iloc[11:].tolist()
        attackers = available[available["position"].isin(captain_call.ARMBAND_POSITIONS)]
        if len(attackers) >= 2:
            captain_id, vice_id = attackers["id"].iloc[0], attackers["id"].iloc[1]
        st.warning(
            "Not enough of your squad is available to field a legal eleven, so FPL will autosub "
            "around it. The reasoning below still applies."
        )

    xi = optimiser.SquadSolution(
        squad_ids=suggested_ids, starting_ids=starting, bench_ids=bench,
        captain_id=captain_id or (starting[0] if starting else 0),
        vice_captain_id=vice_id or (starting[1] if len(starting) > 1 else 0),
        formation=formation or "",
        total_cost=float(suggested["price"].sum()),
        expected_points=float(suggested.loc[suggested["id"].isin(starting), "xp_next"].sum()),
    )
    if captain_id is not None:
        render_html(render_pitch_html(
            suggested.set_index("id", drop=False), _squad_from_solution(xi, next_event)
        ))

    lookup = suggested.set_index("id")
    if bench:
        lines = []
        for order, pid in enumerate(bench, start=1):
            if pid in lookup.index:
                row = lookup.loc[pid]
                lines.append(f"**{order}.** {row['web_name']} · {row['team_short_name']} · {row['position']}")
        if lines:
            st.markdown("**Bench**")
            for line in lines:
                st.markdown(line)

    # ================= SECTION 2 — SUGGESTED TRANSFERS ================
    # One call, one decision. Everything that used to be rendered here —
    # the roll card, the transfer blocks, the "considered and rejected"
    # captions — came from the second engine and is gone with it.
    render_transfer_decision()

    if ranking.entries:
        with st.expander("Sell urgency across all fifteen — worked out before any target"):
            st.caption(
                "0 no reason to sell · 1 minor concern · 2 monitor · 3 genuine candidate · "
                "4 strong sell · 5 urgent. Deliberately blind to the projection: a projection "
                "cannot see an omission, a bid, or a manager declining to commit."
            )
            for d in ranking.ordered:
                st.markdown(
                    f"**{d.sell_urgency}/5 · {d.name}** ({d.sell_urgency_label}) — "
                    f"{d.sell_urgency_reason}"
                )
    if budget:
        st.caption(budget.reason)

    # ================= SECTION 4 — YOUR SQUAD =========================
    # ONE PLAYER = ONE COMPONENT, and there are exactly fifteen of them.
    # The page used to render a player two or three times over — a card
    # here, a dossier there, a corpus write-up underneath — and on a
    # phone that is a scroll with no shape to it. Everything about a
    # player now lives behind his own row, closed until it is asked for.
    _section("Your squad", "All fifteen. Tap a player for the reasoning.")

    matchup_fixtures = cached_matchups(int(next_event))
    player_cases = []
    order = list(starting) + list(bench)
    order += [i for i in suggested_ids if i not in order]
    for pid in order:
        if pid not in lookup.index:
            continue
        row = lookup.loc[pid].copy()
        row["id"] = pid
        run, _ = transfer_case._fixture_run(
            row, fixture_table, next_event, transfer_case.LOOKAHEAD_GAMEWEEKS
        )
        player_cases.append(dossier.build(
            row, next_event, fixtures=matchup_fixtures, fixture_run=run,
            starting=pid in starting, captain=pid == captain_id,
            vice_captain=pid == vice_id,
        ))

    def render_group(label: str, ids: list) -> None:
        if not ids:
            return
        st.markdown(f"**{label}**")
        for pid in ids:
            if pid not in lookup.index:
                continue
            row = lookup.loc[pid]
            name = str(row["web_name"])
            facts = all_facts.get(name) or {
                "player": name, "club": str(row.get("team_short_name", "")),
                "position": str(row.get("position", "")),
                "price": float(row.get("price", 0) or 0),
            }
            render_player(facts, all_status.get(name) or {},
                          media.headshot_html(row.to_dict()))

    render_armband_case(player_cases)
    render_group("Starting XI", list(starting))
    render_group("Bench", list(bench))

    # ================= SECTION 5 — ASK ABOUT MY TEAM ==================
    render_ask_box()

    # --- the footer: what was checked, and how much was read -----------
    st.markdown("---")
    try:
        research = completeness.check(player_cases)
        if not research.ready:
            st.warning(
                f"**Research incomplete.** {research.headline}"
            )
        report = quality_control.run(
            confirmed_ids, scored, next_event,
            transfer_cases=[], player_cases=player_cases,
            bank=bank, free_transfers=free_transfers,
            confirmed_event=confirmed.event,
        )
        run = research_log.load(int(next_event)) or research_log.measure(int(next_event))
        st.caption(
            f"Last researched: {run.finished_display} · {run.coverage_line} · {report.headline}"
        )
        if not report.passed:
            for finding in report.blockers:
                st.error(f"{finding.icon} **{finding.check}** — {finding.detail}")
        with st.expander("Quality checks and research coverage"):
            st.markdown("**Research completeness, player by player**")
            for player in research.worst_first:
                st.markdown(player.line)
                if not player.complete:
                    todo = completeness.next_searches(player, player.name)
                    if todo:
                        st.caption("Still to search: " + " · ".join(f"`{q}`" for q in todo[:4]))
            st.markdown("---")
            for finding in report.findings:
                st.markdown(f"{finding.icon} **{finding.check}** — {finding.detail}")
            if report.passed and not report.warnings:
                st.markdown("Every check passed.")
            gaps = quality_control.corroboration_gaps(scored, confirmed_ids)
            if gaps:
                st.markdown("**Single-sourced claims** (true as far as we know, but only one outlet):")
                for gap in gaps:
                    st.markdown(f"- {gap}")
            if run.unverified:
                st.warning(
                    "Citations outside the verified source list: " + ", ".join(run.unverified)
                )
    except Exception as exc:
        st.caption(f"Couldn't run the pre-publish checks ({exc}).")

    render_html("</div>")


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
    "neutral": ("#5a5a5a", "#f0f0f0", "No strong view"),
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

    tiers = [t for t in ["must_have", "strong", "value", "neutral", "avoid"]
             if (matched["consensus_tier"] == t).any()]
    labels = {
        "must_have": "Must have", "strong": "Strong picks",
        "value": "Value picks", "neutral": "No strong view", "avoid": "Avoid",
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
    # How many transfers to make is a judgement about how broken the squad
    # is and what a hit is worth. That is the app's job, not a slider's --
    # a control there was the app declining to decide and calling it
    # flexibility. Two is the ceiling in a normal week; it rises only when
    # enough of the fifteen is actually unavailable that patching isn't
    # optional.
    owned_now = projected[projected["id"].isin(owned_ids)]
    budget = transfer_budget.decide(owned_now, free_transfers=free_transfers)
    max_transfers = budget.limit
    st.caption(f"**{budget.headline}** {budget.reason}")

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


def render_build_marker() -> None:
    """Which commit is live, printed before anything can go wrong.

    DEPLOYMENT PROOF. The marker used to appear only inside the freshness
    bar, which is reached after the FPL data has loaded — so on a boot
    failure there was no marker at all, and a failed deploy was
    indistinguishable from a stale one. It is now the first thing the page
    writes, before any network call, so the live commit is always
    readable.
    """
    build = version.current()
    render_html(
        "<div style='text-align:right;font-size:.72rem;color:#9aa1ad;"
        "letter-spacing:.04em;margin:-.4rem 0 .2rem 0'>"
        f"build {build.short}"
        + (f" · {build.branch}" if build.branch else "")
        + "</div>")


def render_startup_failure(exc: Exception) -> None:
    """A boot that cannot reach the FPL API must still be a boot.

    THE FIX AT THE HEART OF THIS. An exception escaping the startup
    script does not just show an error page — the hosting platform
    records the build as failed and goes on serving the PREVIOUS build,
    which is precisely the "it stopped redeploying" symptom. Catching it
    turns a failed deployment into a successful one that explains itself,
    and the build marker above proves the new code is live.
    """
    st.error(
        "**The official FPL API could not be reached from this server.**  \n"
        f"`{exc.__class__.__name__}: {exc}`")
    st.markdown(
        "This is a connectivity problem between the host and "
        "fantasy.premierleague.com, not a fault in the app — the build "
        "marker above is this commit, so the deployment itself succeeded. "
        "The API rate-limits datacentre traffic, so it is usually "
        "temporary."
    )
    st.markdown(
        "**What still works.** The research, the transfer plan and the "
        "player write-ups are committed to the repository by the scheduled "
        "workflow, which reaches the API from GitHub. They are current as "
        "of the last successful run."
    )
    decision = load_decision()
    coverage = decision.get("status_coverage") or {}
    if coverage:
        st.caption(
            f"Last checked squad status: {coverage.get('status_checked', '—')} "
            f"· deadline coverage {coverage.get('deadline_coverage', '—')}")
    recommendation = decision.get("recommendation") or {}
    if recommendation.get("verdict"):
        st.markdown(f"**Last committed transfer decision.** "
                    f"{recommendation['verdict']}")
    st.caption("Reload in a few minutes, or press R to rerun.")


def main():
    inject_global_css()
    # Before anything that can fail: which commit is running.
    render_build_marker()
    hero_header()
    try:
        with st.spinner("Pulling the latest FPL data…"):
            players, teams, events, fixtures, state = load_core_data()
    except Exception as exc:
        render_startup_failure(exc)
        return
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

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
    chips,
    consensus,
    explain,
    optimiser,
    price,
    form,
    fixtures as fixtures_analysis,
    injuries,
    rationale,
    squad_builder,
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
    next_event = api.current_event(bootstrap)
    return players, teams, events, fixtures, next_event


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


def render_consensus_panel(scored, squad) -> None:
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
        st.caption(
            "Consensus is an input to the algorithm, not a footnote: must-haves are locked in, "
            "and the rest carry a weighted bonus that competes directly against the projection."
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
        "Transfer hits priced in — a move only appears if it beats its own 4-point cost",
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
            "Known gaps, stated plainly: chip strategy (Wildcard, Bench Boost, Triple Captain, "
            "Free Hit) isn't modelled yet, price changes aren't tracked, and transfers are planned "
            "one gameweek at a time rather than several ahead."
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

    scored = squad_builder.score_players(players, fixtures, teams, next_event)
    solution = squad_builder.recommend_squad(scored, template_weight=rank_strategy_weight())

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


def _anthropic_key() -> str | None:
    """Reads the optional Claude API key.

    Optional on purpose: the free engine handles the common questions, so
    the app is fully usable with no key and no cost. A key only widens
    what can be asked.
    """
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        key = None
    return key or os.environ.get("ANTHROPIC_API_KEY")


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

    if answer.consensus_case:
        st.markdown(f"**What analysts say:** {answer.consensus_case}")
    if answer.consensus_against:
        st.markdown(f"**The case against:** {answer.consensus_against}")


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
            api_key = _anthropic_key()
            with st.spinner("Working it out…"):
                result = ask_engine.ask(
                    question, scored, solution, next_event,
                    api_key=api_key, template_weight=rank_strategy_weight(),
                )
            if result.source == "engine":
                _render_answer(result.answer)
                st.caption("Answered from this week's numbers — no guesswork, and free.")
            elif result.source == "claude":
                st.markdown(result.text)
                st.caption("Answered by Claude, using your squad and this week's research as context.")
            else:
                st.info(result.note)
                st.code(f"FPL question (GW{next_event}): {question.strip()}", language=None)
                st.caption("Copy this (tap the icon) and paste it into your chat with Claude.")


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


def render_starting_xi_tab(players, fixtures, teams, next_event):
    section_header(f"Recommended Starting XI — GW{next_event}", "Best 15 buildable from scratch, with the case for every starter")

    scored = squad_builder.score_players(players, fixtures, teams, next_event)
    solution = squad_builder.recommend_squad(scored, template_weight=rank_strategy_weight())
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
    metrics[0].metric("Projected GW points", f"{xi_xp + captain_bonus:.0f}", help="Starting XI plus the captain's doubled score.")
    metrics[1].metric("Formation", formation)
    metrics[2].metric("Squad cost", f"£{cost:.1f}m", delta=f"£{100.0 - cost:.1f}m spare", delta_color="off")
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

    render_consensus_panel(scored, squad15)
    render_factor_panel()

    report_text, _ = load_report(next_event)

    picks = [
        SquadPick(pid, is_captain=(pid == captain_id), is_vice_captain=(pid == vice_id), multiplier=1, position_order=i + 1)
        for i, pid in enumerate(starters)
    ] + [SquadPick(pid, False, False, 1, 12 + i) for i, pid in enumerate(bench)]
    fake_squad = Squad(
        team_id=0, event=next_event, bank=0.0, team_value=squad15["price"].sum(),
        transfers_made=0, transfers_cost=0, picks=picks,
    )
    render_html(render_pitch_html(squad15, fake_squad))

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

    fixture_table = fixtures_analysis.team_fixture_table(fixtures, teams, next_event, rationale.FIXTURE_WINDOW)
    fixture_gws = list(range(next_event, next_event + rationale.FIXTURE_WINDOW))

    for pos in ["FWD", "MID", "DEF", "GKP"]:
        pos_rows = starters_df[starters_df["position"] == pos]
        if pos_rows.empty:
            continue
        st.markdown(f"**{position_labels[pos]}**")
        for pid, row in pos_rows.iterrows():
            role = " · Captain" if pid == captain_id else (" · Vice-captain" if pid == vice_id else "")
            summary = (
                f"{row['web_name']}{role} — {row['team_short_name']} · £{row['price']:.1f}m · "
                f"{row['xp_next']:.1f} pts projected"
            )
            render_player_deep_dive(row, report_text, fixture_table, fixture_gws, summary=summary)

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


def render_squad_tab(players: pd.DataFrame, team_id: int, next_event: int, events: pd.DataFrame):
    try:
        picks_response = api.get_entry_picks(team_id, next_event)
        entry = api.get_entry(team_id)
    except Exception as e:
        is_deadline_404 = (
            isinstance(e, requests.exceptions.HTTPError)
            and e.response is not None
            and e.response.status_code == 404
        )
        if is_deadline_404:
            deadline = events.loc[next_event, "deadline_time"] if next_event in events.index else None
            when = f" (deadline: {deadline})" if deadline else ""
            st.info(
                f"GW{next_event} picks aren't public yet{when} — the FPL API only exposes a "
                "gameweek's squads once its deadline has passed (so managers can't copy each "
                "other pre-deadline)."
            )
        else:
            st.error(f"Couldn't load team {team_id}: {e}")
        # Whatever went wrong, manual entry still gets you a pitch view today.
        manual_squad = render_manual_squad_entry(players)
        if manual_squad:
            render_html(render_pitch_html(players, manual_squad))
            return manual_squad
        return

    squad = parse_squad(team_id, next_event, picks_response)
    section_header(f"{entry.get('name', 'Your team')} — GW{next_event}")

    c1, c2, c3 = st.columns(3)
    c1.metric("Team value", f"£{squad.team_value:.1f}m")
    c2.metric("Bank", f"£{squad.bank:.1f}m")
    c3.metric("Overall rank", f"{entry.get('summary_overall_rank', '—'):,}" if entry.get("summary_overall_rank") else "—")

    squad_players = players.loc[squad.player_ids].copy()

    render_html(render_pitch_html(squad_players, squad))

    squad_players["captain"] = squad_players["id"].apply(
        lambda pid: "C" if pid == squad.captain_id else ""
    )
    cols = ["web_name", "team_short_name", "position", "price", "form", "status_label", "captain"]
    with st.expander("Squad detail table"):
        st.dataframe(squad_players[cols].sort_values(["position", "web_name"]), width='stretch')

    return squad


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
    scored = squad_builder.score_players(players, fixtures, teams, next_event)
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


def render_fixtures_tab(fixtures, teams, next_event):
    section_header(f"Fixture runs — next {FIXTURE_WINDOW} gameweeks", "Lower FDR = easier run")
    st.caption(f"↔ Swipe the table sideways to see all {FIXTURE_WINDOW} gameweeks.")
    table = fixtures_analysis.team_fixture_table(fixtures, teams, next_event, FIXTURE_WINDOW)
    gw_cols = list(range(next_event, next_event + FIXTURE_WINDOW))
    display_cols = ["team_name"] + gw_cols + ["avg_difficulty", "blank_gameweeks", "double_gameweeks"]
    styled = table[display_cols].style.map(lambda v: fdr_color(v), subset=["avg_difficulty"])
    st.dataframe(styled, width='stretch')

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Best runs (target these teams' players)**")
        best = fixtures_analysis.best_fixture_runs(table)
        st.dataframe(best.style.map(lambda v: fdr_color(v), subset=["avg_difficulty"]), width='stretch')
    with c2:
        st.markdown("**Worst runs (consider avoiding/selling)**")
        worst = fixtures_analysis.worst_fixture_runs(table)
        st.dataframe(worst.style.map(lambda v: fdr_color(v), subset=["avg_difficulty"]), width='stretch')


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


def render_report_tab(next_event):
    section_header(f"Odds & expert take — GW{next_event}", "Live web research, not scraped data")
    text, filename = load_report(next_event)
    if text is None:
        st.info(
            "No report yet. Ask Claude to \"refresh the gameweek report\" — it runs live web "
            "searches for current odds and expert/community sentiment and writes it here, since "
            "direct scraping of bookmaker and forum sites isn't reliable or always allowed."
        )
        return
    if filename != f"gw{next_event}.md":
        st.warning(f"Showing the most recent report available ({filename}), not one for GW{next_event} specifically.")
    st.markdown(text)


def render_transfer_plan(players, fixtures, teams, next_event, squad, free_transfers):
    """The actual weekly decision: who to bring in, and whether a hit pays.

    Solved rather than suggested — the 4-point hit is priced into the
    objective, so a move only appears here if it earns more than it costs.
    """
    st.markdown("#### Recommended move")

    projected = squad_builder.score_players(players, fixtures, teams, next_event)
    owned_ids = [p.player_id for p in squad.picks]

    bank = st.slider(
        "Money in the bank (£m)", 0.0, 10.0, float(squad.bank or 0.0), 0.1,
        help="From your official squad page. Sets what you can afford to spend.",
    )
    max_transfers = st.slider(
        "Most transfers to consider", 1, 4, 2,
        help="Each move beyond your free transfers costs 4 points, which is priced in below.",
    )

    try:
        plan = optimiser.optimise_transfers(
            projected, owned_ids, bank=bank,
            free_transfers=free_transfers, max_transfers=max_transfers,
            template_weight=rank_strategy_weight(),
        )
    except Exception as exc:
        st.info(f"Couldn't solve a transfer plan this week ({exc}). The review list below still applies.")
        return

    if not plan.transfers:
        st.success(
            "**Hold.** No transfer gains enough to be worth making this week — including any that "
            "would cost a hit. Rolling the transfer keeps your options open for next week."
        )
        return

    columns = st.columns(3)
    columns[0].metric("Transfers", plan.transfers)
    columns[1].metric("Points hit", f"−{plan.points_cost}" if plan.points_cost else "None")
    columns[2].metric(
        "Net projected gain", f"+{plan.net_gain:.1f}",
        help="Gain over fielding your best XI as things stand, after subtracting any hit.",
    )

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
    scored = transfers.squad_with_scores(players, fixtures, teams, next_event, FIXTURE_WINDOW)
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
            replacement_cards = [
                player_rank_card(
                    i, row, f"{row['replacement_score']:.2f}", "score",
                    f"£{row['price']:.1f}m · form {row['form']:.1f} · {row['fixture_run_difficulty']:.1f} avg FDR",
                )
                for i, (_, row) in enumerate(replacements.iterrows(), start=1)
            ]
            render_html(render_rank_card_list(replacement_cards))


def main():
    inject_global_css()
    hero_header()
    with st.spinner("Pulling the latest FPL data…"):
        players, teams, events, fixtures, next_event = load_core_data()

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
        tab_names = [tab_names[0], "My Squad"] + tab_names[1:] + ["Transfers"]

    tabs = st.tabs(tab_names)
    tab_map = dict(zip(tab_names, tabs))

    with tab_map["Starting XI"]:
        render_starting_xi_tab(players, fixtures, teams, next_event)

    if team_id:
        with tab_map["My Squad"]:
            squad = render_squad_tab(players, team_id, next_event, events)

    with tab_map["Captaincy"]:
        render_captaincy_tab(players, fixtures, teams, next_event)

    with tab_map["Chips"]:
        render_chips_tab(players, fixtures, teams, next_event)

    with tab_map["Fixtures"]:
        render_fixtures_tab(fixtures, teams, next_event)

    with tab_map["Watchlist"]:
        render_watchlist_tab(players)

    with tab_map["Injuries"]:
        owned_ids = squad.player_ids if squad else None
        render_injuries_tab(players, owned_ids)

    with tab_map["Odds & Expert Take"]:
        render_report_tab(next_event)

    if team_id:
        with tab_map["Transfers"]:
            if squad:
                render_transfers_tab(players, fixtures, teams, next_event, squad)
            else:
                st.info("Transfer suggestions need your squad loaded first — see the My Squad tab.")


if __name__ == "__main__":
    main()

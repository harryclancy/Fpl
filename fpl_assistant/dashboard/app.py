"""FPL Assistant Manager — weekly Streamlit dashboard.

Run with: streamlit run fpl_assistant/dashboard/app.py
"""
import sys
from pathlib import Path

# Allow `streamlit run` to find the package when launched from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import requests
import streamlit as st

from fpl_assistant import api
from fpl_assistant.analysis import (
    captaincy,
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


def render_starting_xi_tab(players, fixtures, teams, next_event):
    section_header(f"Recommended Starting XI — GW{next_event}", "Best 15 buildable from scratch, with the case for every starter")

    scored = squad_builder.score_players(players, fixtures, teams, next_event)
    squad15 = squad_builder.build_squad(scored)
    starters, bench, formation = squad_builder.best_starting_xi(squad15)
    captain_id, vice_id = squad_builder.pick_captain(squad15, starters)

    if is_preseason(players):
        st.info(
            "No match data exists yet this season, so this XI is built from price, ownership, and "
            "fixture difficulty rather than form — it's a 'who to pick from scratch' recommendation, "
            "not tied to your actual squad. Once real form data exists, this switches over "
            "automatically."
        )
    else:
        st.caption(
            "This is the strongest XI buildable from scratch within a £100m budget — not "
            "necessarily who's currently in your squad. Once GW1 unlocks, use My Squad + Transfers "
            "for advice tailored to what you actually own."
        )

    st.caption(f"Formation **{formation}** · squad cost **£{squad15['price'].sum():.1f}m** of £100m budget")

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
    starters_df = starters_df.sort_values(["_order", "squad_score"], ascending=[True, False])

    for pos in ["FWD", "MID", "DEF", "GKP"]:
        pos_rows = starters_df[starters_df["position"] == pos]
        if pos_rows.empty:
            continue
        st.markdown(f"**{position_labels[pos]}**")
        for pid, row in pos_rows.iterrows():
            role = " · Captain" if pid == captain_id else (" · Vice-captain" if pid == vice_id else "")
            summary = f"{row['web_name']}{role} — {row['team_short_name']} · £{row['price']:.1f}m"
            with st.expander(summary):
                photo_col, text_col = st.columns([1, 6])
                with photo_col:
                    render_html(
                        '<div style="width:56px;height:56px;border-radius:50%;overflow:hidden;">'
                        + player_photo_html(row.get("code"), row["web_name"], 56)
                        + "</div>"
                    )
                with text_col:
                    st.markdown(rationale.player_rationale(row, report_text))

    with st.expander(f"Bench ({', '.join(squad15.loc[bench, 'web_name'])})"):
        bench_cols = ["web_name", "team_short_name", "position", "price"]
        st.caption("Cheap enablers to free up budget for the starting XI — minimal impact on your bank.")
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
            "No form data yet this season — score blends price (40%), ownership (25%), and next-"
            "fixture difficulty (35%) as a stand-in until real match data exists."
        )
    else:
        st.caption(
            "Score blends recent form (40%), next-fixture difficulty (30%), and expected goal "
            "involvements (30%). Higher is better."
        )


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


def render_transfers_tab(players, fixtures, teams, next_event, squad):
    section_header("Transfer suggestions")

    try:
        history = api.get_entry_history(squad.team_id)
        free_transfers = transfers.estimate_free_transfers(history["current"], history["chips"])
        st.metric("Estimated free transfers", free_transfers)
        st.caption("Approximate — verify against the official squad page before taking a hit.")
    except Exception:
        pass  # not critical to the rest of the tab

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

    if not team_id:
        st.sidebar.info(
            "Enter your FPL Team ID to see your squad and personalised transfer suggestions. "
            "Sign in at fantasy.premierleague.com, open Pick Team → Gameweek History, and "
            "check the URL: .../entry/1234567/history — that number is your Team ID."
        )

    squad = None
    tab_names = ["Starting XI", "Captaincy", "Fixtures", "Watchlist", "Injuries", "Odds & Expert Take"]
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

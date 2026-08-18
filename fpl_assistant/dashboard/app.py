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
from fpl_assistant.analysis import captaincy, form, fixtures as fixtures_analysis, injuries, transfers
from fpl_assistant.config import FPL_TEAM_ID
from fpl_assistant.dashboard.pitch import render_pitch_html
from fpl_assistant.dashboard.styles import hero_header, inject_global_css
from fpl_assistant.models import attach_team_names, events_df, fixtures_df, parse_squad, players_df, teams_df
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


def render_squad_tab(players: pd.DataFrame, team_id: int, next_event: int, events: pd.DataFrame):
    try:
        picks_response = api.get_entry_picks(team_id, next_event)
        entry = api.get_entry(team_id)
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            deadline = events.loc[next_event, "deadline_time"] if next_event in events.index else None
            when = f" (deadline: {deadline})" if deadline else ""
            st.info(
                f"GW{next_event} picks aren't public yet{when} — the FPL API only exposes a "
                "gameweek's squads once its deadline has passed (so managers can't copy each "
                "other pre-deadline). Check back after the deadline."
            )
        else:
            st.error(f"Couldn't load team {team_id}: {e}")
        return
    except Exception as e:
        st.error(f"Couldn't load team {team_id}: {e}")
        return

    squad = parse_squad(team_id, next_event, picks_response)
    st.subheader(f"{entry.get('name', 'Your team')} — GW{next_event}")

    c1, c2, c3 = st.columns(3)
    c1.metric("Team value", f"£{squad.team_value:.1f}m")
    c2.metric("Bank", f"£{squad.bank:.1f}m")
    c3.metric("Overall rank", f"{entry.get('summary_overall_rank', '—'):,}" if entry.get("summary_overall_rank") else "—")

    squad_players = players.loc[squad.player_ids].copy()

    st.markdown(render_pitch_html(squad_players, squad), unsafe_allow_html=True)

    squad_players["captain"] = squad_players["id"].apply(
        lambda pid: "C" if pid == squad.captain_id else ""
    )
    cols = ["web_name", "team_short_name", "position", "price", "form", "status_label", "captain"]
    with st.expander("Squad detail table"):
        st.dataframe(squad_players[cols].sort_values(["position", "web_name"]), use_container_width=True)

    return squad


def render_captaincy_tab(players, fixtures, teams, next_event):
    st.subheader(f"Captaincy candidates — GW{next_event}")
    picks = captaincy.captaincy_candidates(players, fixtures, teams, next_event)
    st.dataframe(picks, use_container_width=True)
    st.caption(
        "Score blends recent form (40%), next-fixture difficulty (30%), and expected goal "
        "involvements (30%). Higher is better."
    )


def render_fixtures_tab(fixtures, teams, next_event):
    st.subheader(f"Fixture runs — next {FIXTURE_WINDOW} gameweeks")
    table = fixtures_analysis.team_fixture_table(fixtures, teams, next_event, FIXTURE_WINDOW)
    gw_cols = list(range(next_event, next_event + FIXTURE_WINDOW))
    display_cols = ["team_name"] + gw_cols + ["avg_difficulty", "blank_gameweeks", "double_gameweeks"]
    st.dataframe(table[display_cols], use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Best runs (target these teams' players)**")
        st.dataframe(fixtures_analysis.best_fixture_runs(table), use_container_width=True)
    with c2:
        st.markdown("**Worst runs (consider avoiding/selling)**")
        st.dataframe(fixtures_analysis.worst_fixture_runs(table), use_container_width=True)


def render_watchlist_tab(players):
    st.subheader("Player watchlist")
    position = st.selectbox("Position", [None, "GKP", "DEF", "MID", "FWD"], format_func=lambda x: x or "All")

    t1, t2, t3 = st.tabs(["In form", "Best value", "Differentials"])
    with t1:
        st.dataframe(form.in_form_players(players, position=position), use_container_width=True)
    with t2:
        st.dataframe(form.best_value_players(players, position=position), use_container_width=True)
    with t3:
        st.dataframe(form.differentials(players), use_container_width=True)


def render_injuries_tab(players, owned_ids):
    st.subheader("Injury & availability news")
    st.markdown("**Your squad**")
    st.dataframe(injuries.flagged_players(players, owned_only_ids=owned_ids), use_container_width=True)
    st.markdown("**Everyone flagged this week**")
    st.dataframe(injuries.flagged_players(players), use_container_width=True)


def render_report_tab(next_event):
    st.subheader(f"Odds & expert take — GW{next_event}")
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
    st.subheader("Transfer suggestions")

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
    st.dataframe(weaknesses, use_container_width=True)

    weak_names = weaknesses["web_name"].tolist()
    chosen = st.selectbox("See replacement options for:", weak_names)
    if chosen:
        player_id = scored[scored["web_name"] == chosen]["id"].iloc[0]
        budget = st.slider("Extra budget available (£m, on top of selling price)", 0.0, 5.0, 0.0, 0.1)
        st.dataframe(
            transfers.suggest_replacements(scored, squad, player_id, budget), use_container_width=True
        )


def main():
    inject_global_css()
    hero_header()
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
    tab_names = ["Captaincy", "Fixtures", "Watchlist", "Injuries", "Odds & Expert Take"]
    if team_id:
        tab_names = ["My Squad"] + tab_names + ["Transfers"]

    tabs = st.tabs(tab_names)
    tab_map = dict(zip(tab_names, tabs))

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

    if team_id and squad:
        with tab_map["Transfers"]:
            render_transfers_tab(players, fixtures, teams, next_event, squad)


if __name__ == "__main__":
    main()

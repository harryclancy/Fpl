"""Renders a squad as an actual football pitch, not just a table.

Pure HTML/CSS injected via st.markdown — no JS, no external CSS/JS
dependencies. Player avatars are colored initials (see media.py for why:
Streamlit strips the onerror handler a real-photo fallback would need,
so a real photo attempt would risk showing a raw broken-image icon
instead of degrading cleanly).
"""
import pandas as pd

from fpl_assistant.dashboard.media import MEDIA_CSS, player_photo_html, team_crest_html
from fpl_assistant.dashboard.theme import club_colours
from fpl_assistant.models import Squad

POSITION_ORDER = ["FWD", "MID", "DEF", "GKP"]  # top (attack) to bottom (keeper) on the pitch

POSITION_ACCENT = {
    "GKP": "#f5c518",
    "DEF": "#4da3ff",
    "MID": "#00ff87",
    "FWD": "#ff4d6d",
}

PITCH_CSS = """
<style>
.pitch-wrap {
    background:
        repeating-linear-gradient(
            to bottom,
            #1e7a3d 0, #1e7a3d 60px,
            #218844 60px, #218844 120px
        );
    border-radius: 16px;
    padding: 28px 12px 16px 12px;
    position: relative;
    border: 2px solid rgba(255,255,255,0.25);
    box-shadow: 0 8px 24px rgba(0,0,0,0.35);
}
.pitch-line-circle {
    width: 130px; height: 130px;
    border: 2px solid rgba(255,255,255,0.35);
    border-radius: 50%;
    position: absolute;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    z-index: 0;
}
.pitch-halfway {
    position: absolute;
    left: 0; right: 0; top: 50%;
    border-top: 2px solid rgba(255,255,255,0.35);
    z-index: 0;
}
.pitch-row {
    display: flex;
    justify-content: center;
    gap: 18px;
    flex-wrap: wrap;
    position: relative;
    z-index: 1;
    margin: 14px 0;
}
.player-card {
    background: rgba(13, 13, 26, 0.82);
    border-radius: 12px;
    padding: 8px 8px 6px 8px;
    width: 104px;
    text-align: center;
    border-top: 3px solid var(--accent, #00ff87);
    backdrop-filter: blur(2px);
    box-shadow: 0 4px 10px rgba(0,0,0,0.4);
}
.player-photo-box {
    position: relative;
    width: 52px; height: 52px;
    margin: 0 auto 5px auto;
    border-radius: 50%;
    /* Club-coloured ring: identity at a glance, and it reads as a badge
       rather than a cropped photo floating on the pitch. */
    box-shadow: 0 0 0 2px var(--accent, #00ff87), 0 2px 8px rgba(0,0,0,0.45);
}
.armband {
    position: absolute;
    top: -4px; right: -4px;
    width: 20px; height: 20px;
    border-radius: 50%;
    font-size: 11px;
    font-weight: 800;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #0e0e1a;
    border: 2px solid #0e0e1a;
}
.armband-c { background: #f5c518; }
.armband-v { background: #d7d7de; }
.player-name {
    font-size: 12px;
    font-weight: 700;
    color: #fff;
    line-height: 1.2;
    margin-top: 2px;
    overflow-wrap: break-word;
}
.player-meta {
    font-size: 10.5px;
    color: #cfd3dc;
    margin-top: 1px;
}
.bench-strip {
    background: #23233a;
    border-radius: 12px;
    padding: 14px 12px 8px 12px;
    margin-top: 4px;
    border: 1px dashed rgba(255,255,255,0.18);
}
.bench-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #9a9ab0;
    margin-bottom: 8px;
    font-weight: 700;
}
</style>
"""


def _player_card_html(row: pd.Series, badge: str | None) -> str:
    # Accent by club rather than by position. Position is already obvious
    # from where the card sits on the pitch, so spending colour on it says
    # nothing; club colour instead makes a triple-up on one team visible
    # at a glance, which is the constraint people actually trip over.
    accent, _ = club_colours(row.get("team_short_name"))
    face = player_photo_html(
        row.get("code"), row["web_name"], team_short_name=row.get("team_short_name")
    )

    badge_html = ""
    if badge == "C":
        badge_html = '<div class="armband armband-c">C</div>'
    elif badge == "V":
        badge_html = '<div class="armband armband-v">V</div>'

    return f"""
    <div class="player-card" style="--accent: {accent};">
      <div class="player-photo-box">
        {face}
        {badge_html}
      </div>
      <div class="player-name">{row['web_name']}</div>
      <div class="player-meta">{team_crest_html(row.get('team_code'), str(row.get('team_short_name') or ''), size_px=11)} £{row['price']:.1f}m</div>
    </div>
    """


def render_pitch_html(squad_players: pd.DataFrame, squad: Squad) -> str:
    """squad_players must be the players table filtered/indexed to this squad's ids."""
    starters = [p for p in squad.picks if p.position_order <= 11]
    bench = sorted([p for p in squad.picks if p.position_order > 11], key=lambda p: p.position_order)

    rows_html = ""
    for pos in POSITION_ORDER:
        pos_picks = [p for p in starters if squad_players.loc[p.player_id, "position"] == pos]
        if not pos_picks:
            continue
        cards = ""
        for pick in pos_picks:
            row = squad_players.loc[pick.player_id]
            badge = "C" if pick.is_captain else ("V" if pick.is_vice_captain else None)
            cards += _player_card_html(row, badge)
        rows_html += f'<div class="pitch-row">{cards}</div>'

    bench_cards = ""
    for pick in bench:
        row = squad_players.loc[pick.player_id]
        bench_cards += _player_card_html(row, None)

    html = f"""
    {PITCH_CSS}
    {MEDIA_CSS}
    <div class="pitch-wrap">
      <div class="pitch-line-circle"></div>
      <div class="pitch-halfway"></div>
      {rows_html}
    </div>
    <div class="bench-strip">
      <div class="bench-label">Bench</div>
      <div class="pitch-row" style="margin:0;">{bench_cards}</div>
    </div>
    """
    return html

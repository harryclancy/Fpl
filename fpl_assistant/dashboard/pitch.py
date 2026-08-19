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
    /* A softer, lighter turf than the dark theme used. A saturated green
       that looked right against near-black is garish surrounded by white,
       and it fights the club colours it exists to showcase. */
    background:
        repeating-linear-gradient(
            to bottom,
            #dff0e2 0, #dff0e2 62px,
            #d6ebda 62px, #d6ebda 124px
        );
    border-radius: 18px;
    padding: 30px 14px 20px 14px;
    position: relative;
    border: 1px solid #c6dfcc;
    box-shadow: 0 2px 6px rgba(21,19,26,0.06);
}
.pitch-line-circle {
    width: 132px; height: 132px;
    border: 2px solid rgba(255,255,255,0.85);
    border-radius: 50%;
    position: absolute;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    z-index: 0;
}
.pitch-halfway {
    position: absolute;
    left: 0; right: 0; top: 50%;
    border-top: 2px solid rgba(255,255,255,0.85);
    z-index: 0;
}
.pitch-row {
    display: flex;
    justify-content: center;
    gap: 18px;
    flex-wrap: wrap;
    position: relative;
    z-index: 1;
    margin: 15px 0;
}
.player-card {
    background: rgba(255,255,255,0.96);
    border-radius: 13px;
    padding: 9px 8px 7px 8px;
    width: 106px;
    text-align: center;
    border: 1px solid rgba(21,19,26,0.07);
    border-top: 3px solid var(--accent, #38003c);
    box-shadow: 0 2px 6px rgba(21,19,26,0.10);
}
.player-photo-box {
    position: relative;
    width: 52px; height: 52px;
    margin: 0 auto 6px auto;
    border-radius: 50%;
    /* Club-coloured ring: identity at a glance, and it reads as a badge
       rather than a cropped photo floating on the pitch. */
    box-shadow: 0 0 0 2px var(--accent, #38003c), 0 1px 4px rgba(21,19,26,0.18);
}
.player-name {
    font-size: 12px;
    font-weight: 600;
    color: #15131a;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    letter-spacing: -0.01em;
}
.player-meta {
    font-size: 10.5px;
    color: #5f5a6b;
    margin-top: 2px;
    font-variant-numeric: tabular-nums;
}
.armband {
    position: absolute;
    top: -3px; right: -3px;
    width: 20px; height: 20px;
    border-radius: 50%;
    font-size: 11px;
    font-weight: 800;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 3;
    border: 2px solid #ffffff;
    box-shadow: 0 1px 3px rgba(21,19,26,0.25);
}
.armband-c { background: #ffc93c; color: #3a2a00; }
.armband-v { background: #ffffff; color: #38003c; }
.bench-strip {
    margin-top: 14px;
    padding: 13px 14px 11px 14px;
    background: #faf9fc;
    border: 1px solid #e6e2ee;
    border-radius: 14px;
}
.bench-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #8b8598;
    font-weight: 700;
    margin-bottom: 9px;
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

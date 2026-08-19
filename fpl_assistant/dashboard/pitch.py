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
POSITION_ROW_LABELS = {"FWD": "up top", "MID": "in midfield", "DEF": "at the back", "GKP": "in goal"}

POSITION_ACCENT = {
    "GKP": "#f5c518",
    "DEF": "#4da3ff",
    "MID": "#00ff87",
    "FWD": "#ff4d6d",
}

PITCH_CSS = """
<style>
.pitch-wrap {
    /* Mown stripes run across the pitch, as they do at a ground. A softer,
       lighter turf than the dark theme used: a saturated green that looked
       right against near-black is garish surrounded by white, and it fights
       the club colours it exists to showcase. */
    background:
        repeating-linear-gradient(
            to bottom,
            #e2f1e4 0, #e2f1e4 54px,
            #d8ecdc 54px, #d8ecdc 108px
        );
    border-radius: 18px;
    padding: 26px 14px 22px 14px;
    position: relative;
    overflow: hidden;
    border: 1px solid #c3ddc9;
    box-shadow: 0 2px 8px rgba(21,19,26,0.08);
    /* Bands are spread down the pitch so the shape reads as the formation
       rather than as a stack of rows. */
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    gap: 6px;
    min-height: 520px;
}

/* --- Markings ------------------------------------------------------- */
.pitch-markings { position: absolute; inset: 0; z-index: 0; pointer-events: none; }
.pitch-markings > * { position: absolute; border-color: rgba(255,255,255,0.9); }
.pitch-box {
    left: 50%; transform: translateX(-50%);
    width: 54%; height: 78px;
    border: 2px solid rgba(255,255,255,0.9);
}
.pitch-box-top { top: -2px; border-top: none; border-radius: 0 0 4px 4px; }
.pitch-box-bottom { bottom: -2px; border-bottom: none; border-radius: 4px 4px 0 0; }
.pitch-sixyard {
    left: 50%; transform: translateX(-50%);
    width: 26%; height: 32px;
    border: 2px solid rgba(255,255,255,0.9);
}
.pitch-sixyard-top { top: -2px; border-top: none; }
.pitch-sixyard-bottom { bottom: -2px; border-bottom: none; }
.pitch-halfway {
    left: 0; right: 0; top: 50%;
    border-top: 2px solid rgba(255,255,255,0.9);
}
.pitch-circle {
    width: 128px; height: 128px;
    border: 2px solid rgba(255,255,255,0.9);
    border-radius: 50%;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
}
.pitch-spot {
    width: 6px; height: 6px;
    background: rgba(255,255,255,0.9);
    border-radius: 50%;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
}

.formation-badge {
    position: absolute;
    top: 10px; right: 14px;
    z-index: 2;
    background: rgba(255,255,255,0.92);
    color: #15131a;
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 0.06em;
    padding: 2px 9px;
    border-radius: 999px;
    border: 1px solid rgba(21,19,26,0.08);
}

/* --- Bands ----------------------------------------------------------- */
.pitch-band { position: relative; z-index: 1; }
.band-tag {
    display: block;
    text-align: center;
    font-size: 9.5px;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    font-weight: 700;
    color: rgba(21,19,26,0.42);
    margin-bottom: 3px;
}
.pitch-row {
    display: flex;
    justify-content: center;
    gap: 10px;
    flex-wrap: wrap;
    position: relative;
    z-index: 1;
}

/* --- Player cards ----------------------------------------------------- */
.player-card {
    background: rgba(255,255,255,0.97);
    border-radius: 12px;
    padding: 8px 6px 6px 6px;
    width: 96px;
    text-align: center;
    border: 1px solid rgba(21,19,26,0.07);
    border-top: 3px solid var(--accent, #38003c);
    box-shadow: 0 2px 6px rgba(21,19,26,0.14);
}
.player-photo-box {
    position: relative;
    width: 46px; height: 46px;
    margin: 0 auto 5px auto;
    border-radius: 50%;
    /* Club-coloured ring: identity at a glance, and it reads as a badge
       rather than a cropped photo floating on the pitch. */
    box-shadow: 0 0 0 2px var(--accent, #38003c), 0 1px 4px rgba(21,19,26,0.2);
}
.player-name {
    font-size: 11.5px;
    font-weight: 600;
    color: #15131a;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    letter-spacing: -0.01em;
}
.player-meta {
    font-size: 10px;
    color: #5f5a6b;
    margin-top: 1px;
    font-variant-numeric: tabular-nums;
}
.armband {
    position: absolute;
    top: -3px; right: -3px;
    width: 19px; height: 19px;
    border-radius: 50%;
    font-size: 10.5px;
    font-weight: 800;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 3;
    border: 2px solid #ffffff;
    box-shadow: 0 1px 3px rgba(21,19,26,0.28);
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

@media (max-width: 640px) {
    .pitch-wrap { min-height: 460px; padding: 20px 4px 16px 4px; }
    /* Five across is the widest band FPL allows, and it has to fit on one
       line: a midfield that wraps to 4+1 reads as a different formation
       from the one you picked, which is the whole thing this view exists
       to show. Sized so 5 cards plus gaps clear a 390px phone. */
    .player-card { width: 64px; padding: 5px 3px 4px 3px; }
    .player-photo-box { width: 34px; height: 34px; margin-bottom: 4px; }
    .player-name { font-size: 9.5px; }
    .player-meta { font-size: 8.5px; }
    .pitch-row { gap: 4px; flex-wrap: nowrap; }
    .pl-club-chip { font-size: 8px; padding: 0 3px; margin-right: 3px; }
    .armband { width: 16px; height: 16px; font-size: 9px; }
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
    """squad_players must be the players table filtered/indexed to this squad's ids.

    Laid out as the formation actually is: keeper on his line at the
    bottom, then defence, midfield and attack in evenly spaced bands up
    the pitch, each row labelled with how many are in it. The previous
    version stacked the same rows without markings or spacing, so a 3-4-3
    and a 5-3-2 looked identical -- you could read the formation off the
    caption but not off the picture, which defeats the point of drawing a
    pitch at all.
    """
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
        label = POSITION_ROW_LABELS.get(pos, pos)
        rows_html += (
            f'<div class="pitch-band">'
            f'<span class="band-tag">{len(pos_picks)} {label}</span>'
            f'<div class="pitch-row">{cards}</div>'
            f"</div>"
        )

    bench_cards = ""
    for pick in bench:
        row = squad_players.loc[pick.player_id]
        bench_cards += _player_card_html(row, None)

    formation = "-".join(
        str(sum(1 for p in starters if squad_players.loc[p.player_id, "position"] == pos))
        for pos in ("DEF", "MID", "FWD")
    )

    return f"""
    {PITCH_CSS}
    {MEDIA_CSS}
    <div class="pitch-wrap">
      <div class="pitch-markings">
        <div class="pitch-box pitch-box-top"></div>
        <div class="pitch-sixyard pitch-sixyard-top"></div>
        <div class="pitch-halfway"></div>
        <div class="pitch-circle"></div>
        <div class="pitch-spot"></div>
        <div class="pitch-box pitch-box-bottom"></div>
        <div class="pitch-sixyard pitch-sixyard-bottom"></div>
      </div>
      <div class="formation-badge">{formation}</div>
      {rows_html}
    </div>
    <div class="bench-strip">
      <div class="bench-label">Bench — in the order they'd come on</div>
      <div class="pitch-row" style="margin:0;">{bench_cards}</div>
    </div>
    """

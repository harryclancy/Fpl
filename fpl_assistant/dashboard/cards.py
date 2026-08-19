"""Rich HTML card list for ranked player tables (captaincy, watchlist) —
photo + crest + key stat, instead of a plain dataframe. Same graceful
photo/crest fallback as the pitch view (see media.py).
"""
import pandas as pd

from fpl_assistant.dashboard.media import MEDIA_CSS, player_photo_html, team_crest_html

CARD_LIST_CSS = """
<style>
.rank-card-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px; }
.rank-card {
    display: flex; align-items: center; gap: 13px;
    background: #ffffff;
    border: 1px solid #e6e2ee;
    border-radius: 12px;
    padding: 11px 15px;
    box-shadow: 0 1px 2px rgba(21,19,26,0.04);
}
.rank-num {
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 17px; font-weight: 700; color: #8b8598;
    width: 22px; text-align: center; flex-shrink: 0;
    font-variant-numeric: tabular-nums;
}
.rank-photo { position: relative; width: 44px; height: 44px; flex-shrink: 0; }
.rank-info { flex: 1; min-width: 0; }
.rank-name { font-weight: 600; color: #15131a; font-size: 14.5px; letter-spacing: -0.005em; }
.rank-meta { font-size: 11.5px; color: #5f5a6b; margin-top: 2px; }
.rank-score { text-align: right; flex-shrink: 0; padding-left: 6px; }
.rank-score .value {
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 22px; font-weight: 700; line-height: 1.1;
    font-variant-numeric: tabular-nums;
}
.rank-score .label {
    font-size: 9px; color: #8b8598; text-transform: uppercase; letter-spacing: 0.07em;
}
</style>
"""

SCORE_GOOD = "#0a7d4f"
SCORE_WARN = "#8a5a00"
SCORE_BAD = "#b0203c"


def player_rank_card(
    rank: int, row: pd.Series, score_value: str, score_label: str, meta_line: str, score_color: str = SCORE_GOOD
) -> str:
    photo = player_photo_html(
        row.get("code"), row["web_name"], size_px=44,
        team_short_name=row.get("team_short_name"),
    )
    crest = team_crest_html(row.get("team_code"), str(row.get("team_short_name") or ""), size_px=12)
    return f"""
    <div class="rank-card">
      <div class="rank-num">{rank}</div>
      <div class="rank-photo">{photo}</div>
      <div class="rank-info">
        <div class="rank-name">{row['web_name']}</div>
        <div class="rank-meta">{crest}{row['position']} · {meta_line}</div>
      </div>
      <div class="rank-score">
        <div class="value" style="color: {score_color};">{score_value}</div>
        <div class="label">{score_label}</div>
      </div>
    </div>
    """


def render_rank_card_list(cards_html: list[str]) -> str:
    return f"{CARD_LIST_CSS}{MEDIA_CSS}<div class='rank-card-list'>{''.join(cards_html)}</div>"

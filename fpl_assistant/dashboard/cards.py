"""Rich HTML card list for ranked player tables (captaincy, watchlist) —
photo + crest + key stat, instead of a plain dataframe. Same graceful
photo/crest fallback as the pitch view (see media.py).
"""
import pandas as pd

from fpl_assistant.dashboard.media import MEDIA_CSS, player_photo_html, team_crest_html

CARD_LIST_CSS = """
<style>
.rank-card-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.rank-card {
    display: flex; align-items: center; gap: 12px;
    background: linear-gradient(145deg, #171729, #1d1d36);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    padding: 10px 14px;
}
.rank-num {
    font-size: 15px; font-weight: 800; color: #6b6b85;
    width: 20px; text-align: center; flex-shrink: 0;
}
.rank-photo { position: relative; width: 44px; height: 44px; flex-shrink: 0; }
.rank-photo img, .rank-photo .photo-fallback {
    width: 44px; height: 44px; border-radius: 50%; object-fit: cover;
    border: 2px solid rgba(255,255,255,0.35);
}
.rank-photo .photo-fallback { background: #2a2a3d; color: #fff; font-size: 13px; }
.rank-info { flex: 1; min-width: 0; }
.rank-name { font-weight: 700; color: #fff; font-size: 14px; }
.rank-meta { font-size: 11.5px; color: #9a9ab0; margin-top: 1px; }
.rank-score { text-align: right; flex-shrink: 0; padding-left: 4px; }
.rank-score .value { font-size: 16px; font-weight: 800; color: #00ff85; }
.rank-score .label { font-size: 9px; color: #7d7d95; text-transform: uppercase; letter-spacing: 0.5px; }
</style>
"""


def player_rank_card(rank: int, row: pd.Series, score_value: str, score_label: str, meta_line: str) -> str:
    photo = player_photo_html(row.get("code"), row["web_name"], size_px=44)
    crest = team_crest_html(row.get("team_code"), "", size_px=12)
    return f"""
    <div class="rank-card">
      <div class="rank-num">{rank}</div>
      <div class="rank-photo">{photo}</div>
      <div class="rank-info">
        <div class="rank-name">{row['web_name']}</div>
        <div class="rank-meta">{crest}{row['team_short_name']} · {row['position']} — {meta_line}</div>
      </div>
      <div class="rank-score">
        <div class="value">{score_value}</div>
        <div class="label">{score_label}</div>
      </div>
    </div>
    """


def render_rank_card_list(cards_html: list[str]) -> str:
    return f"{CARD_LIST_CSS}{MEDIA_CSS}<div class='rank-card-list'>{''.join(cards_html)}</div>"

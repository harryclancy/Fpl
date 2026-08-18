"""Player photo / team crest URL construction, shared by every HTML card
renderer in the dashboard (pitch view, captaincy cards, etc).

These CDN URLs can't be verified from this environment's sandbox (network
egress to resources.premierleague.com is blocked here), so every use is
paired with an `onerror` handler that swaps in a clean fallback badge
rather than ever showing a broken-image icon.
"""
import pandas as pd

PLAYER_PHOTO_URL = "https://resources.premierleague.com/premierleague25/photos/players/110x140/{code}.png"
TEAM_CREST_URL = "https://resources.premierleague.com/premierleague25/badges/50/t{code}.png"


def initials(name: str) -> str:
    parts = str(name).split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return str(name)[:2].upper()


def player_photo_html(code, web_name: str, size_px: int = 52) -> str:
    """A circular player photo with an initials-avatar fallback if the
    image 404s. Wrap in a container with position: relative for badges.
    """
    fallback = initials(web_name)
    if pd.isna(code):
        return f'<div class="photo-fallback" style="display:flex;">{fallback}</div>'
    url = PLAYER_PHOTO_URL.format(code=int(code))
    return (
        f'<img class="photo-img" src="{url}" alt="" '
        f"onerror=\"this.style.display='none'; this.nextElementSibling.style.display='flex';\">"
        f'<div class="photo-fallback">{fallback}</div>'
    )


def team_crest_html(code, short_name: str = "", size_px: int = 18) -> str:
    """A small team crest icon with a text-badge fallback if it 404s.

    Pass `short_name=""` when a team abbreviation is already shown right
    next to this crest in the caller's markup, so the fallback doesn't
    duplicate it — it'll just render nothing rather than a broken image.
    """
    fallback = short_name
    if pd.isna(code):
        return f'<span class="crest-fallback">{fallback}</span>' if fallback else ""
    url = TEAM_CREST_URL.format(code=int(code))
    return (
        f'<img class="crest-img" src="{url}" alt="{fallback}" width="{size_px}" height="{size_px}" '
        f"onerror=\"this.style.display='none'; this.nextElementSibling.style.display='inline';\">"
        f'<span class="crest-fallback" style="display:none;">{fallback}</span>'
    )


MEDIA_CSS = """
<style>
.photo-img { width: 100%; height: 100%; object-fit: cover; display: block; }
.photo-fallback {
    display: none;
    width: 100%; height: 100%;
    border-radius: 50%;
    align-items: center;
    justify-content: center;
    font-weight: 700;
}
.crest-img { vertical-align: middle; margin-right: 4px; }
.crest-fallback {
    display: inline-block;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.5px;
    opacity: 0.85;
    margin-right: 4px;
}
</style>
"""

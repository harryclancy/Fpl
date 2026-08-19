"""Player faces and club badges.

Real photos, with a fallback that cannot show a broken-image icon.

The obvious approach — an `<img>` with an `onerror` handler swapping in an
avatar — does not work here: Streamlit's markdown sanitiser strips inline
event-handler attributes, so a 404 leaves the browser's default broken
image and nothing can intercept it. That's why this previously shipped as
initials-only.

The fix is to stop using `<img>` and stack two layers instead. A tinted
club-coloured tile holds the player's initials, and the photo sits above
it as a `background-image` on an absolutely-positioned overlay. If the
photo loads it covers the tile; if the URL 404s the overlay simply paints
nothing and the initials show through. No JavaScript, no broken-image
icon, and the failure mode is a design rather than a defect — which
matters because the photo CDN has no entry for every newly-promoted
squad player.
"""
from __future__ import annotations

import pandas as pd

from fpl_assistant.dashboard.theme import club_colours, readable_on

# The Premier League's own photo CDN, keyed by the `code` field on each
# element (not `id` — those differ, and using `id` silently returns 404s
# for everyone).
PHOTO_BASE = "https://resources.premierleague.com/premierleague/photos/players"
PHOTO_SIZE = "250x250"


def initials(name: str) -> str:
    parts = str(name).replace(".", " ").split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return str(name)[:2].upper()


def photo_url(code) -> str | None:
    if code is None or pd.isna(code):
        return None
    try:
        return f"{PHOTO_BASE}/{PHOTO_SIZE}/p{int(code)}.png"
    except (TypeError, ValueError):
        return None


def player_photo_html(
    code, web_name: str, size_px: int = 52, team_short_name: str | None = None
) -> str:
    """A circular player face, tinted to their club and captioned with
    their initials underneath in case the photo is missing."""
    primary, secondary = club_colours(team_short_name)
    text_colour = readable_on(primary)
    url = photo_url(code)
    overlay = (
        f'<span class="pl-face-photo" style="background-image:url(\'{url}\')"></span>'
        if url
        else ""
    )
    return (
        f'<span class="pl-face" style="background:linear-gradient(150deg,{primary},{secondary});'
        f'color:{text_colour}">'
        f'<span class="pl-face-initials">{initials(web_name)}</span>{overlay}</span>'
    )


def team_crest_html(code, short_name: str = "", size_px: int = 18) -> str:
    """A club-coloured chip carrying the three-letter short name.

    Reads as a badge rather than plain text, which is what makes a list of
    fifteen players scannable by club at a glance.
    """
    if not short_name:
        return ""
    primary, secondary = club_colours(short_name)
    return (
        f'<span class="pl-club-chip" style="background:linear-gradient(135deg,{primary},{secondary});'
        f'color:{readable_on(primary)}">{short_name}</span>'
    )


MEDIA_CSS = """
<style>
.pl-face {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    aspect-ratio: 1 / 1;
    border-radius: 50%;
    overflow: hidden;
    font-weight: 700;
    font-size: 0.85em;
    letter-spacing: 0.02em;
    box-shadow: inset 0 0 0 1px rgba(255,255,255,0.16);
}
/* Initials sit underneath; the photo overlay covers them when it loads.
   A 404 paints nothing, so the initials remain visible. */
.pl-face-initials { position: relative; z-index: 0; }
.pl-face-photo {
    position: absolute;
    inset: 0;
    z-index: 1;
    background-size: cover;
    /* Bias toward the top of the frame: PL portraits are head-and-shoulders,
       so centring crops the face awkwardly at small sizes. */
    background-position: 50% 12%;
    background-repeat: no-repeat;
}
.pl-club-chip {
    display: inline-block;
    padding: 1px 6px;
    border-radius: 5px;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.04em;
    line-height: 1.5;
    vertical-align: middle;
}
</style>
"""

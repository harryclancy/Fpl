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
    box-shadow: inset 0 0 0 1px rgba(21,19,26,0.10);
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
    margin-right: 5px;
}
</style>
"""


# --- one image pipeline, keyed to the CURRENT club -----------------------

def current_headshot(player: dict) -> dict:
    """The one function every part of the app asks for a player's face.

    PART G. The photo itself was never the problem — it is keyed on the
    player's own `code`, which does not change when he moves. The club
    did: the tile behind the face is tinted with his club's colours and
    captioned with his club's initials, so a record carrying last
    season's team painted a Manchester City player in Everton blue.

    So the club is taken from the CURRENT bootstrap on every call and
    nothing about a player's appearance is remembered between runs. There
    is no image cache to invalidate, which is the most reliable way of
    never serving a stale one.
    """
    return {
        "code": player.get("code"),
        "name": str(player.get("web_name") or player.get("name") or ""),
        "team": str(player.get("team_short_name") or player.get("team") or ""),
        "url": photo_url(player.get("code")),
    }


def headshot_html(player: dict, size_px: int = 52) -> str:
    """A face rendered from the current record, or an honest fallback.

    A WRONG IMAGE IS WORSE THAN NO IMAGE. Where the photo CDN has no
    entry — a new signing, a promoted squad player — the tile shows his
    initials on his current club's colours rather than reaching for
    something that might be somebody else.
    """
    current = current_headshot(player)
    return player_photo_html(current["code"], current["name"], size_px,
                             current["team"])


def stale_image(cached_team: str, current_team: str) -> bool:
    """Would a remembered image now be wrong?

    Kept as an explicit test even though nothing here caches, because the
    rule is what matters: if the club a picture was chosen for is not the
    club he plays for, the picture is not reused.
    """
    return bool(cached_team) and bool(current_team) and cached_team != current_team

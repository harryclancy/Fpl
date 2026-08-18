"""Player/team avatar rendering.

We tried real photos from the Premier League's photo CDN with a JS
`onerror` fallback to an initials avatar — but Streamlit's markdown
sanitizer strips inline event-handler attributes (`onerror` etc.) from
HTML passed through st.markdown, even with unsafe_allow_html=True, so a
failed image request just shows a browser-default broken-image icon with
no way to catch it and swap in the fallback. Confirmed live: the request
fails (naturalWidth stays 0) but the onerror handler never fires because
the attribute isn't present in the rendered DOM at all.

Rather than gamble on an unverifiable CDN URL pattern breaking silently
in production, this renders colored initials avatars as the actual
design — the same pattern Slack/Discord/Linear use for missing photos,
not a degraded fallback. Zero risk of a broken-image icon, consistent
look every time.
"""
import pandas as pd

AVATAR_PALETTE = [
    "#e90052", "#04f5ff", "#00ff85", "#f5c518", "#4da3ff", "#ff4d6d", "#9b5de5", "#38003c",
]


def initials(name: str) -> str:
    parts = str(name).split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return str(name)[:2].upper()


def _avatar_color(seed) -> str:
    if pd.isna(seed):
        return AVATAR_PALETTE[0]
    return AVATAR_PALETTE[int(seed) % len(AVATAR_PALETTE)]


def player_photo_html(code, web_name: str, size_px: int = 52) -> str:
    """A colored circular initials avatar, sized to fill its container."""
    color = _avatar_color(code if pd.notna(code) else hash(web_name))
    return f'<div class="photo-fallback" style="display:flex; background:{color};">{initials(web_name)}</div>'


def team_crest_html(code, short_name: str = "", size_px: int = 18) -> str:
    """A small text badge for the team short name.

    Pass `short_name=""` when a team abbreviation is already shown right
    next to this badge in the caller's markup, to avoid duplicating it —
    it'll render nothing.
    """
    if not short_name:
        return ""
    return f'<span class="crest-fallback">{short_name}</span>'


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
    color: #0e0e1a;
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

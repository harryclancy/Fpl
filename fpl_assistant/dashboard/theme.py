"""Design tokens: club colours and the app's own palette.

Club colour is the fastest identity cue in football — you recognise a
shirt before you read a name — so every player element in the app is tinted
by their club rather than by a generic accent. That also does real work
beyond decoration: on a pitch view of fifteen players, colour is what lets
you see at a glance that you're triple-stacked on one team.

Keyed by the FPL three-letter short name, which is stable across seasons
in a way club full names are not ("Spurs" vs "Tottenham Hotspur").
"""
from __future__ import annotations

# Premier League brand palette, used for the app's own chrome.
PURPLE = "#38003c"
PINK = "#e90052"
GREEN = "#00ff85"
CYAN = "#04f5ff"

# Surface tones for the dark theme. Kept as a small ramp rather than
# ad-hoc hex values so panels, cards and the page background stay in a
# deliberate relationship instead of drifting apart per component.
INK_900 = "#0b0b14"
INK_800 = "#12121f"
INK_700 = "#181829"
INK_600 = "#1f1f33"
INK_500 = "#2a2a42"
TEXT = "#f2f2f7"
TEXT_MUTED = "rgba(242,242,247,0.62)"
TEXT_FAINT = "rgba(242,242,247,0.40)"

# (primary, secondary) per club. Primary is the shirt colour people
# picture; secondary is the trim, used for gradients and accents.
CLUB_COLOURS: dict[str, tuple[str, str]] = {
    "ARS": ("#EF0107", "#063672"),
    "AVL": ("#670E36", "#95BFE5"),
    "BOU": ("#DA291C", "#000000"),
    "BRE": ("#E30613", "#FBB800"),
    "BHA": ("#0057B8", "#FFCD00"),
    "BUR": ("#6C1D45", "#99D6EA"),
    "CHE": ("#034694", "#DBA111"),
    "COV": ("#5CBFEB", "#003366"),
    "CRY": ("#1B458F", "#C4122E"),
    "EVE": ("#003399", "#FFFFFF"),
    "FUL": ("#1B1B1B", "#CC0000"),
    "HUL": ("#F5A12D", "#000000"),
    "IPS": ("#3A64A3", "#DE2C37"),
    "LEE": ("#FFCD00", "#1D428A"),
    "LEI": ("#003090", "#FDBE11"),
    "LIV": ("#C8102E", "#00B2A9"),
    "LLU": ("#FA4616", "#1C2C5B"),
    "MCI": ("#6CABDD", "#1C2C5B"),
    "MUN": ("#DA291C", "#FBE122"),
    "NEW": ("#241F20", "#F1BE48"),
    "NFO": ("#DD0000", "#FFFFFF"),
    "NOR": ("#FFF200", "#00A650"),
    "SHU": ("#EE2737", "#000000"),
    "SOU": ("#D71920", "#130C0E"),
    "SUN": ("#EB172B", "#211E1F"),
    "TOT": ("#132257", "#FFFFFF"),
    "WHU": ("#7A263A", "#1BB1E7"),
    "WOL": ("#FDB913", "#231F20"),
}

DEFAULT_CLUB_COLOURS = ("#4b4b6b", "#7a7a9c")


def club_colours(short_name: str | None) -> tuple[str, str]:
    """Primary and secondary colour for a club, falling back to neutral
    greys for anything not in the map (promoted sides, renamed clubs)."""
    if not short_name:
        return DEFAULT_CLUB_COLOURS
    return CLUB_COLOURS.get(str(short_name).upper(), DEFAULT_CLUB_COLOURS)


def club_gradient(short_name: str | None, angle: str = "135deg") -> str:
    primary, secondary = club_colours(short_name)
    return f"linear-gradient({angle}, {primary}, {secondary})"


def readable_on(hex_colour: str) -> str:
    """Black or white text, whichever stays legible on this background.

    Wolves' amber and Newcastle's near-black both appear in the same UI,
    so a fixed text colour is unreadable on one of them whichever you
    pick. Uses perceived luminance rather than a naive average, since the
    eye is far more sensitive to green than to blue.
    """
    colour = hex_colour.lstrip("#")
    if len(colour) != 6:
        return "#ffffff"
    try:
        red, green, blue = (int(colour[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "#ffffff"
    luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255
    return "#0b0b14" if luminance > 0.6 else "#ffffff"

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

# Surface ramp for the light theme. Kept as a deliberate scale rather than
# ad-hoc hex values so panels, cards and the page background stay in a
# fixed relationship instead of drifting apart per component.
#
# Note none of these is pure grey — each carries a trace of the brand
# violet. Neutral greys next to a saturated purple read as dirty, and the
# whole surface looks accidental rather than designed.
PAPER = "#ffffff"
SURFACE_50 = "#faf9fc"
SURFACE_100 = "#f4f2f8"
SURFACE_200 = "#ebe8f2"
SURFACE_300 = "#ded9e8"
BORDER = "#e6e2ee"
BORDER_STRONG = "#d3cce0"

TEXT = "#15131a"
TEXT_MUTED = "#5f5a6b"
TEXT_FAINT = "#8b8598"

# Semantic colours, chosen to clear 4.5:1 on white rather than for
# vividness. The neon green that carried the old dark theme is unreadable
# here, so it survives only as a background tint behind darker text.
POSITIVE = "#0a7d4f"
POSITIVE_TINT = "#e6f7ef"
WARNING = "#8a5a00"
WARNING_TINT = "#fdf3e0"
NEGATIVE = "#b0203c"
NEGATIVE_TINT = "#fdeaee"
ACCENT_TINT = "#f3ebf7"

# Retained so any straggling reference keeps working while the light
# theme beds in.
INK_900 = TEXT
INK_800 = SURFACE_100
INK_700 = SURFACE_200
INK_600 = SURFACE_300
INK_500 = BORDER_STRONG

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

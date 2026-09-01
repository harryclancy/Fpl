"""Stage 5: reading an article, not just its headline.

RSS gives a title and usually a two-sentence teaser. That is enough to
decide whether a page is worth reading and nowhere near enough to know
what a manager actually said. "Slot on Szoboszlai" in a headline tells you
a quote exists; only the body tells you whether it was "he trained fully"
or "we will assess him".

So the top-ranked candidates get fetched and stripped to text. Everything
here is stdlib — `html.parser` plus regexes — because adding BeautifulSoup
or trafilatura would be another dependency that can fail a free install,
and the job is narrow enough not to need them.

The extraction is deliberately crude but conservative: strip script and
style, take the text, and if what comes back is too short or looks like
navigation, say so rather than storing a menu as an article body.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

# Under this many characters, whatever came back is a stub, a paywall
# notice or a cookie wall — not an article.
MIN_BODY_CHARS = 400
MAX_BODY_CHARS = 12_000

# Tags whose contents are never article text.
SKIP_TAGS = {"script", "style", "nav", "header", "footer", "aside", "form",
             "noscript", "svg", "button", "select", "iframe"}

# Lines that are navigation furniture rather than writing. Compared after
# lowercasing and stripping.
BOILERPLATE = (
    "accept all cookies", "manage cookies", "sign in", "subscribe", "newsletter",
    "share this article", "read more", "advertisement", "skip to main content",
    "cookie policy", "privacy policy", "terms of use", "all rights reserved",
    "follow us on", "download the app", "click here",
)

# Topic tags. The point is not classification for its own sake — it is so
# a player's evidence can be checked for BREADTH, because eight articles
# all about the same transfer rumour is not the same as eight articles
# covering minutes, role, fitness and fixtures.
TOPIC_PATTERNS = {
    "team news": ("team news", "predicted line", "predicted xi", "starting xi",
                  "line-up", "lineup", "selection", "expected to start", "set to start"),
    "press conference": ("press conference", "told reporters", "speaking to", "said:",
                         "pre-match", "presser", "media duties"),
    "injury": ("injury", "injured", "ruled out", "sidelined", "fitness", "scan",
               "hamstring", "knock", "doubt", "recovery", "return to training"),
    "suspension": ("suspended", "suspension", "red card", "ban", "sent off"),
    "transfer": ("transfer", "bid", "medical", "loan", "signing", "deal", "fee",
                 "contract", "release clause"),
    "match report": ("match report", "full-time", "report:", "highlights", "1-0", "2-1"),
    "tactics": ("tactic", "formation", "role", "deeper", "false nine", "inverted",
                "press", "system", "shape"),
    "set pieces": ("set piece", "free kick", "corner", "penalt", "spot kick", "dead ball"),
    "statistics": ("xg", "xa", "xgi", "expected goals", "underlying", "per 90",
                   "shots", "big chance", "defcon", "defensive contribution"),
    "fpl advice": ("fpl", "fantasy premier league", "captain", "differential",
                   "wildcard", "triple captain", "bench boost", "free hit",
                   "transfer tips", "ownership", "price change", "scout picks"),
    "rotation": ("rotation", "rotated", "rested", "squad depth", "europa", "champions league",
                 "carabao", "midweek"),
    "fixtures": ("fixture", "run of games", "next three", "next five", "schedule",
                 "double gameweek", "blank gameweek", "clean sheet"),
}


class _TextExtractor(HTMLParser):
    """Collects visible text, skipping the tags that never carry prose."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text)


@dataclass
class Extracted:
    """The result of trying to read a page. Failure states its reason."""

    text: str = ""
    ok: bool = False
    reason: str = ""
    topics: tuple[str, ...] = ()

    @property
    def chars(self) -> int:
        return len(self.text)


def topics_in(text: str) -> tuple[str, ...]:
    """Which research dimensions this text actually speaks to."""
    lowered = text.lower()
    return tuple(topic for topic, terms in TOPIC_PATTERNS.items()
                 if any(term in lowered for term in terms))


def from_html(html: str) -> Extracted:
    """Page source to article text, or a stated reason why not.

    Returning `ok=False` with a reason matters more than it looks: a
    paywall, a cookie wall and a 404 body all produce *some* text, and
    storing that as an article body is how a research corpus fills up with
    consent notices that mention no player at all.
    """
    if not html or len(html) < 120:
        return Extracted(reason="page was empty or truncated")

    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # malformed markup is common and must not propagate
        return Extracted(reason="markup could not be parsed")

    lines = []
    for part in parser.parts:
        lowered = part.lower()
        if any(marker in lowered for marker in BOILERPLATE):
            continue
        if len(part) < 3:
            continue
        lines.append(part)

    text = re.sub(r"\s+", " ", " ".join(lines)).strip()
    if len(text) < MIN_BODY_CHARS:
        return Extracted(text=text, reason=f"only {len(text)} characters of prose")
    return Extracted(text=text[:MAX_BODY_CHARS], ok=True, topics=topics_in(text))

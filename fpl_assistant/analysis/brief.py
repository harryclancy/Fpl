"""One player, judged — not summarised.

The write-ups this replaces answered "what did we find about him?". A
manager does not need that. He needs "why should this player be in my
team this week?", which is a different question with a different shape:
evidence, then interpretation, then comparison, then a decision he can
act on.

The difference is not length. "Thiago starts. His place looks very
secure. SUN (H)." is three true statements and no judgement. What was
missing is the step where a fixture becomes an opportunity, a price
becomes efficient or wasteful, a good record becomes a reason to hold
through a bad week, and an alternative on the bench becomes the reason
this one plays instead.

So every section here is built from a named judgement rather than from a
sentence someone else wrote:

    WILL HE PLAY        selection record, sample size, new-club status
    WHY THIS WEEK       the fixture INTERPRETED for his position
    THE CASE AGAINST    always populated; a write-up with no doubt in it
                        is not analysis
    VERSUS THE ALTERNATIVES   the bench he is picked ahead of, the
                        transfer he would be sold for
    THE NEXT FOUR       whether this is a one-week problem or a trend
    THE DECISION        a label a manager can act on

Nothing here reads a player's name, and nothing quotes an article
directly — the research is the input, the write-up is the judgement.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --- the vocabulary of a judgement ---------------------------------------

SECURE, LIKELY, UNCERTAIN, DOUBTFUL, OUT = (
    "secure", "likely", "uncertain", "doubtful", "out")

HIGH, MEDIUM, LOW = "High", "Medium", "Low"

# Decisions a manager can actually carry out. Deliberately compound: the
# selection call and the squad call are separate questions and a write-up
# that answers only one of them leaves the reader still deciding.
START_HOLD = "START AND HOLD"
START_MONITOR = "START, BUT MONITOR"
BENCH_HOLD = "BENCH AND HOLD"
BENCH_MONITOR = "BENCH, AND MONITOR"
KEEP_THROUGH = "KEEP THROUGH THE TOUGH FIXTURE"
HOLD_REASSESS = "HOLD THIS WEEK, REASSESS NEXT"
SELL_IF = "SELL IF THE MINUTES CONCERN IS CONFIRMED"
SELL_NOW = "SELL"
CAPTAIN_CALL = "CAPTAIN"
VICE_CALL = "VICE-CAPTAIN, AND HOLD"

# FPL's fixture difficulty is 1 (easiest) to 5 (hardest). These bands are
# the whole reason a write-up can say what a fixture MEANS rather than
# printing its three-letter code and leaving the reader to translate.
FIXTURE_BANDS = (
    (2.0, "one of the friendlier fixtures on the board"),
    (2.6, "a favourable fixture"),
    (3.2, "a fair fixture"),
    (3.7, "an awkward fixture"),
    (4.3, "a hard fixture"),
    (5.1, "one of the toughest fixtures of the week"),
)

POSITION_WORDS = {"GKP": "goalkeeper", "DEF": "defender",
                  "MID": "midfielder", "FWD": "forward"}

ATTACKING = ("MID", "FWD")
DEFENSIVE = ("GKP", "DEF")


WORDS = {0: "no", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
         6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def _count(number: int, noun: str = "game", whole: bool = False) -> str:
    """Numbers as a person would write them, not as a counter emits them."""
    if whole and number == 2:
        return f"both {noun}s"
    word = WORDS.get(number, str(number))
    return f"{word} {noun}{'' if number == 1 else 's'}"


def _started_of(inputs) -> str:
    """"both games", or "two of three" — never "two games of two games"."""
    if inputs.starts == inputs.team_games:
        return _count(inputs.team_games, whole=True)
    return f"{WORDS.get(inputs.starts, inputs.starts)} of {_count(inputs.team_games)}"


def _article(amount: float) -> str:
    """'an £8.0m defender', not 'a £8.0m defender'."""
    return "an" if f"{amount:.1f}".startswith(("8", "11", "18")) else "a"


def fixture_phrase(difficulty: float) -> str:
    for ceiling, phrase in FIXTURE_BANDS:
        if difficulty < ceiling:
            return phrase
    return FIXTURE_BANDS[-1][1]


@dataclass
class Fixture:
    opponent: str = ""
    home: bool = True
    difficulty: float = 3.0

    @property
    def label(self) -> str:
        return f"{self.opponent} ({'H' if self.home else 'A'})"

    @property
    def venue(self) -> str:
        return "at home" if self.home else "away"


@dataclass
class Alternative:
    """Someone he is being picked ahead of, or sold for.

    `detail` carries the reason the transfer engine gave, so a write-up
    that raises a better-looking replacement can also say what happened
    to it. Naming a gap and leaving it open is how a page ends up
    arguing with its own recommendation.
    """

    name: str
    detail: str = ""
    five_gw: float = 0.0
    # The engine's own five-gameweek difference for THIS swap. Two
    # separately-computed totals subtracted from each other disagreed with
    # the engine's own figure, so the write-up quoted +1.1 and the reason
    # underneath it quoted +5.0.
    delta: float | None = None
    rejected_because: str = ""


@dataclass
class BriefInputs:
    """Everything the judgement is allowed to use.

    A flat record on purpose. If a consideration is not here it cannot
    reach the prose, which is what stops an article about another player
    leaking into this one's write-up.
    """

    player: str = ""
    club: str = ""
    club_name: str = ""
    position: str = ""
    price: float = 0.0

    # Will he play?
    starts: int = 0
    minutes_played: int = 0
    team_games: int = 0
    availability: str = "a"
    chance_of_playing: float | None = None
    minutes_category: str = "Unassessed"
    # Last completed season, at the club he is at NOW. This is what makes
    # "established starter" sayable in gameweek three: nobody has a large
    # in-season sample yet, and refusing to use the prior season means
    # every player in the game is a Medium forever. It does not carry
    # across a transfer -- see new_club_evidence.
    prior_minutes: int = 0
    prior_appearances: int = 0
    new_club_evidence: str = ""      # a published line saying he has moved
    # THE CURRENT STATUS PASS, when one has been run. It is authoritative:
    # if the freshness layer has looked at predicted line-ups and what the
    # manager said, the write-up must not reach its own separate verdict
    # from the same evidence and land somewhere else.
    status: dict = field(default_factory=dict)
    rotation_evidence: str = ""
    injury_evidence: str = ""
    transfer_evidence: str = ""

    # The fixtures, already scored.
    fixtures: list[Fixture] = field(default_factory=list)

    # How good his team is, and this week's opponent, on FPL's own
    # 1000-1400 strength scale, expressed as a percentile so the language
    # is calibrated rather than asserted.
    team_attack_rank: float | None = None      # 0 worst .. 1 best
    team_defence_rank: float | None = None
    opponent_attack_rank: float | None = None
    opponent_defence_rank: float | None = None

    # Form and underlying numbers.
    points_per_game: float = 0.0
    positional_ppg: float = 0.0     # the median for his position
    total_points: int = 0
    xgi90: float = 0.0
    positional_xgi90: float = 0.0
    xgc90: float = 0.0
    defcon90: float = 0.0
    set_pieces: bool = False
    penalties: bool = False

    # What the model expects.
    projection: float = 0.0
    five_gw: float = 0.0
    positional_five_gw: float = 0.0

    # Where he sits in the squad and what the plan does with him.
    on_bench: bool = False
    captain: bool = False
    vice: bool = False
    being_sold: bool = False
    sell_urgency: float = 0.0
    hold_strength: float = 0.0

    # Real alternatives, not hypothetical ones.
    bench_alternatives: list[Alternative] = field(default_factory=list)
    transfer_alternatives: list[Alternative] = field(default_factory=list)

    # --- derived ---------------------------------------------------------

    @property
    def attacker(self) -> bool:
        return self.position in ATTACKING

    @property
    def this_week(self) -> Fixture | None:
        return self.fixtures[0] if self.fixtures else None

    @property
    def thin_sample(self) -> bool:
        """Two games is not a season. Any minutes verdict rests on it."""
        return self.team_games <= 4

    @property
    def established(self) -> bool:
        """Did he hold this shirt down last season, at THIS club?

        A transfer voids it: minutes, role and set-piece duty earned
        somewhere else prove nothing about the new dressing room, which is
        the distinction that stops a summer signing being described as a
        nailed starter off a record he built elsewhere.
        """
        return (not self.new_club_evidence
                and self.prior_minutes >= 1800
                and self.prior_appearances >= 20)

    @property
    def start_share(self) -> float:
        if not self.team_games:
            return 0.0
        return min(1.0, self.starts / self.team_games)

    @property
    def minutes_per_game(self) -> float:
        if not self.team_games:
            return 0.0
        return self.minutes_played / self.team_games


# --- 1. will he actually play? -------------------------------------------

def playing_verdict(inputs: BriefInputs) -> tuple[str, str]:
    """How likely he is to start, and the sentence that says why.

    FIT IS NOT THE SAME AS STARTING. A player can be perfectly available
    and still be a coin flip for the eleven, and the old write-ups
    collapsed the two — "his place looks very secure on the selection
    record" was printed for a man with two appearances at a club he had
    just joined.

    A transfer resets this. Starts, minutes, role and set-piece duty at a
    previous club prove nothing about the new one, so until there is
    evidence from the new club his minutes are treated as unproven
    however impressive the raw numbers look.
    """
    fresh = inputs.status or {}
    if fresh.get("outlook"):
        return _from_status(inputs, fresh)

    if inputs.availability in ("i", "s", "u", "n"):
        reason = {"i": "he is injured", "s": "he is suspended",
                  "u": "he is unavailable",
                  "n": "he is not in the squad"}[inputs.availability]
        return OUT, f"He will not play: {reason}."

    chance = inputs.chance_of_playing
    if chance is not None and chance <= 25:
        return DOUBTFUL, (
            f"FPL puts him at {chance:.0f}% to feature, so he is closer to a "
            f"non-starter than a pick.")
    if inputs.availability == "d" or (chance is not None and chance <= 75):
        return UNCERTAIN, (
            "He carries a fitness flag, so the starting call will not be "
            "settled until the team sheet.")

    if inputs.injury_evidence:
        return UNCERTAIN, (
            "An injury has been reported this week, so his minutes are not "
            "the given the selection record makes them look.")

    if inputs.new_club_evidence:
        return (LIKELY if inputs.start_share >= 0.75 else UNCERTAIN), (
            f"He has joined {inputs.club_name or inputs.club} recently, so his "
            f"role there is not yet established — a starting record built "
            f"somewhere else proves nothing about this dressing room.")

    if inputs.rotation_evidence:
        return UNCERTAIN, (
            "Rotation is being reported around him, which is exactly the risk "
            "a raw start count cannot see.")

    share, per_game = inputs.start_share, inputs.minutes_per_game
    if share >= 0.9 and per_game >= 80:
        if inputs.established:
            return SECURE, (
                f"He has started {_started_of(inputs)} this season on top "
                f"of {inputs.prior_minutes:,} minutes at the club last year, "
                f"so the place is his rather than a hot fortnight.")
        if inputs.thin_sample:
            return LIKELY, (
                f"He has started {_count(inputs.team_games, whole=True)} and "
                f"played almost every minute — as strong a signal as "
                f"{_count(inputs.team_games)} can give, which is real but not "
                f"yet a pattern.")
        return SECURE, (
            f"He has started {_started_of(inputs)} and averages "
            f"{per_game:.0f} minutes, which is a settled place rather than a "
            f"run of luck.")
    if share >= 0.6 or per_game >= 60:
        return LIKELY, (
            f"He has started {_started_of(inputs)} and averages "
            f"{per_game:.0f} minutes — likely to play, without being "
            f"guaranteed.")
    if inputs.minutes_played == 0 and inputs.team_games:
        return UNCERTAIN, (
            f"He has not played a minute in {_count(inputs.team_games)}, so "
            f"anything he offers is theoretical until he is picked.")
    return UNCERTAIN, (
        f"{_count(inputs.starts, noun='start')} in "
        f"{_count(inputs.team_games)} leaves his place open to question.")


# --- 2. why do I want him THIS gameweek? ---------------------------------

# The freshness layer's vocabulary, mapped onto this module's. One
# status, two names for it, and the translation lives in one place.
STATUS_PLAYING = {
    "Very likely to start": SECURE, "Likely to start": LIKELY,
    "50-50": UNCERTAIN, "Likely bench": UNCERTAIN,
    "Very unlikely to start": DOUBTFUL, "Out": OUT,
}


def _from_status(inputs: BriefInputs, fresh: dict) -> tuple[str, str]:
    """The playing verdict, read off the Current Status Pass.

    Not recomputed. The freshness layer has already weighed the predicted
    line-ups, the manager's words and the appearance record; reaching a
    second verdict here from the same evidence is how a page ends up
    telling a manager two different things about one player.
    """
    outlook = fresh.get("outlook", "")
    playing = STATUS_PLAYING.get(outlook, UNCERTAIN)
    reasons = [r for r in (fresh.get("reasons") or []) if r]
    vetoes = [v for v in (fresh.get("vetoes") or []) if v]
    lead = vetoes[0] if vetoes else (reasons[0] if reasons else "")
    minutes = fresh.get("minutes_label", "")
    sentence = f"{outlook} this week"
    if minutes:
        sentence += f" ({minutes})"
    if lead:
        sentence += f" — {lead}"
    return playing, sentence + "."


def _rank_phrase(rank: float | None, superlative: str, comparative: str,
                 weak_superlative: str, weak_comparative: str) -> str:
    """Where a side sits in the league, said the way a person would say it.

    Four explicit forms rather than one adjective bent into shape: "a
    strongest attacking side" is what happens when a superlative is
    reused as a comparative, and it appeared on the page.
    """
    if rank is None:
        return ""
    if rank >= 0.8:
        return f"one of the {superlative} sides in the league"
    if rank >= 0.6:
        return f"a {comparative} side"
    if rank <= 0.2:
        return f"one of the {weak_superlative} sides in the league"
    if rank <= 0.4:
        return f"a {weak_comparative} side"
    return ""


def fixture_case(inputs: BriefInputs) -> str:
    """What this week's fixture MEANS for a player in his position.

    "Sunderland at home" is a fact a manager already had. What he does
    not have is what it implies: which side of the pitch it helps, how
    much, and whether his own team is good enough to use it.
    """
    fixture = inputs.this_week
    if not fixture:
        return ""
    phrase = fixture_phrase(fixture.difficulty)
    where = f"{fixture.opponent} {fixture.venue}"

    if inputs.attacker:
        opponent = _rank_phrase(
            _agreeing(inputs.opponent_defence_rank, fixture.difficulty),
            "strongest defensive", "solid defensive",
            "leakiest defensive", "leakier defensive")
        sentence = f"{where} is {phrase} for an attacker"
        if opponent:
            sentence += f", against {opponent}"
        sentence += "."
        sentence += _own_team_clause(
            inputs.club_name or inputs.club, inputs.team_attack_rank,
            strong="one of the strongest attacking sides in the league, so the "
                   "chances should be there to be taken",
            weak="not a side that creates a great deal, which caps what even a "
                 "kind fixture can produce")
        return sentence

    opponent = _rank_phrase(
        _agreeing(inputs.opponent_attack_rank, fixture.difficulty),
        "most dangerous attacking", "dangerous attacking",
        "least threatening attacking", "less threatening attacking")
    sentence = f"{where} is {phrase} for a clean sheet"
    if opponent:
        sentence += f", against {opponent}"
    sentence += "."
    sentence += _own_team_clause(
        inputs.club_name or inputs.club, inputs.team_defence_rank,
        strong="one of the meanest defensive sides in the league, which is the "
               "part that carries over from week to week",
        weak="not a reliable source of clean sheets, so the returns lean on "
             "what he does himself rather than on the shut-out")
    return sentence


def _agreeing(rank: float | None, difficulty: float) -> float | None:
    """The opponent's rating, but only when it agrees with the fixture.

    FPL publishes two independent views of an opponent: an editorial 1-5
    difficulty and a 1000-1400 strength table. They can disagree, and
    when they did the write-up printed both — "a favourable fixture,
    against one of the strongest defensive sides in the league" — which
    is one sentence arguing with itself. The difficulty is the number the
    projection model uses, so it wins, and the other simply goes unsaid
    rather than being reported as a contradiction.
    """
    if rank is None:
        return None
    easy_fixture = difficulty <= 2.6
    hard_fixture = difficulty >= 3.7
    weak_opponent = rank <= 0.4
    strong_opponent = rank >= 0.6
    if easy_fixture and strong_opponent:
        return None
    if hard_fixture and weak_opponent:
        return None
    return rank


def _own_team_clause(club: str, rank: float | None, strong: str,
                     weak: str) -> str:
    """His own team's quality, but only when it actually says something."""
    if rank is None:
        return ""
    if rank >= 0.75:
        return f" {club} are {strong}."
    if rank <= 0.3:
        return f" {club} are {weak}."
    return ""


def returns_case(inputs: BriefInputs) -> str:
    """What he does with the opportunity when he gets it."""
    parts = []
    if inputs.attacker and inputs.xgi90:
        if inputs.positional_xgi90 and inputs.xgi90 >= inputs.positional_xgi90 * 1.3:
            parts.append(
                f"His {inputs.xgi90:.2f} expected goal involvements per 90 are "
                f"well clear of the typical {_position(inputs.position)}")
    if not inputs.attacker and inputs.defcon90 >= 8:
        parts.append(
            f"He averages {inputs.defcon90:.1f} defensive contributions per 90, "
            f"which is a floor that does not depend on a clean sheet")
    if inputs.penalties:
        parts.append("he takes the penalties, which is the single largest "
                     "swing available to a player at his price")
    elif inputs.set_pieces:
        parts.append("he is on set pieces, which adds returns the open-play "
                     "numbers do not capture")
    if not parts:
        return ""
    text = parts[0]
    for extra in parts[1:]:
        text += f", and {extra}"
    return text.rstrip(".") + "."


def value_case(inputs: BriefInputs) -> str:
    """Whether the money is doing work, in both directions."""
    if not inputs.price or not inputs.positional_five_gw or not inputs.five_gw:
        return ""
    ratio = inputs.five_gw / inputs.positional_five_gw
    if ratio >= 1.25:
        return (f"At £{inputs.price:.1f}m he projects well ahead of a typical "
                f"{_position(inputs.position)} over the next five, so the money "
                f"is earning its place.")
    return ""


def poor_value(inputs: BriefInputs) -> str:
    """The other half of the money question, for the case against."""
    if not inputs.price or not inputs.positional_five_gw or not inputs.five_gw:
        return ""
    if inputs.five_gw / inputs.positional_five_gw > 0.8:
        return ""
    return (f"at £{inputs.price:.1f}m he projects below a typical "
            f"{_position(inputs.position)} over the next five, so the real "
            f"question is not whether he plays but whether the money is doing "
            f"enough")


def opportunity_case(inputs: BriefInputs, playing: str = SECURE) -> str:
    """The floor a nailed attacker has even when the numbers are cold.

    Written for the striker with two points a game and a kind fixture:
    the case for him is not his form, it is that he is the one on the
    pitch when the chances arrive.

    Which is why it is gated on him being on the pitch. Telling a manager
    that a player the freshness layer expects to be benched has "access
    to the chances" is the write-up arguing with its own status line.
    """
    fixture = inputs.this_week
    if playing not in (SECURE, LIKELY):
        return ""
    if not (inputs.attacker and fixture) or fixture.difficulty > 3.0:
        return ""
    return ("Whatever else is wrong, he is on the pitch when the chances "
            "come, and that access is the case for owning him this week.")


def _position(code: str) -> str:
    return POSITION_WORDS.get(code, "player")


# --- 3. the case against -------------------------------------------------

def case_against(inputs: BriefInputs, playing: str) -> list[str]:
    """What could make this decision wrong.

    Always populated. A write-up in which every selected player is
    perfect is not analysis, it is a team sheet with adjectives, and the
    reader learns nothing he can act on. Where nothing is actually wrong,
    the honest answer is the size of the sample the confidence rests on.
    """
    against = []

    if playing in (OUT, DOUBTFUL):
        against.append("he may not play at all, which makes everything else "
                       "about him academic")
    elif playing == UNCERTAIN:
        against.append("his minutes are the weak point rather than his quality")

    if inputs.injury_evidence:
        against.append("an injury has been reported this week")
    if inputs.rotation_evidence:
        against.append("rotation is being talked about around him")
    if inputs.transfer_evidence:
        against.append("there is transfer talk around him, which tends to "
                       "precede a change in role before it precedes a move")

    fixture = inputs.this_week
    if fixture and fixture.difficulty >= 3.7:
        subject = ("the defence he is facing" if inputs.attacker
                   else "the attack he is facing")
        against.append(
            f"{fixture.opponent} {fixture.venue} is a genuinely hard week and "
            f"{subject} will limit the ceiling")

    enabler = inputs.price <= 4.6
    if inputs.points_per_game and inputs.positional_ppg:
        if inputs.points_per_game <= inputs.positional_ppg * 0.7:
            tail = ("which is the whole of what he offers"
                    if enabler else
                    f"and £{inputs.price:.1f}m is a lot to have tied up in it")
            against.append(
                f"his {inputs.points_per_game:.1f} points a game is poor for "
                f"the position, {tail}")
    if (inputs.attacker and inputs.xgi90 and inputs.positional_xgi90
            and inputs.xgi90 <= inputs.positional_xgi90 * 0.7):
        against.append("the underlying attacking numbers are thin, so the "
                       "returns are not obviously waiting to arrive")
    # Not for an enabler: he is not bought to out-score anyone, and
    # saying his money is idle when his money is the point is backwards.
    money = "" if enabler else poor_value(inputs)
    if money:
        against.append(money)

    fresh = inputs.status or {}
    tally = fresh.get("lineups") or {}
    if tally.get("benched", 0) + tally.get("omitted", 0):
        against.append(
            f"the current predicted line-ups are the problem — {tally['summary']}")
    if fresh.get("manager_reading") in ("undecided", "will not start"):
        against.append("the manager has not committed to him starting")
    if fresh.get("stale") and not tally.get("readable"):
        against.append(
            "his starting status has not been confirmed by anything published "
            "recently, which is an absence of news rather than good news")

    if inputs.new_club_evidence:
        against.append("he is new to the club, and a role can look settled for "
                       "a fortnight and then not be")
    elif inputs.thin_sample and playing in (SECURE, LIKELY) and not inputs.established:
        against.append(
            f"the whole case for his minutes rests on "
            f"{_count(inputs.team_games)}, which is not yet a pattern")

    # A premium is a claim on the rest of the squad, and it belongs in the
    # doubts even when the player is excellent — especially then, because
    # nobody questions the obvious pick until the season is half gone.
    if inputs.price >= 11.0:
        against.append(
            f"£{inputs.price:.1f}m is a large share of the budget resting on "
            f"one player, and it only pays while he keeps returning")

    best_bench = inputs.bench_alternatives[0] if inputs.bench_alternatives else None
    if best_bench and best_bench.five_gw > inputs.five_gw:
        against.append(
            f"{best_bench.name} projects higher over the next five, so the "
            f"selection is closer than it looks")

    if not against:
        against.append(
            "there is nothing published against him this week, which is a "
            "thinner kind of comfort than it sounds — it is an absence of bad "
            "news rather than evidence of good")
    return against


# --- 4 & 5. keep or sell, and the next four ------------------------------

def run_direction(inputs: BriefInputs) -> tuple[str, str]:
    """Does the fixture run improve, or is this week the good part?

    The question that decides whether a hard fixture is a reason to sell
    or a week to sit through. Selling a settled asset over one match is
    how a manager spends a transfer and then spends another buying him
    back.
    """
    fixtures = inputs.fixtures
    if len(fixtures) < 3:
        return "unknown", ""
    now = fixtures[0].difficulty
    later = sum(f.difficulty for f in fixtures[1:4]) / len(fixtures[1:4])
    labels = " → ".join(f.label for f in fixtures[:4])
    if now - later >= 0.6:
        return "improves", (
            f"The run improves after this week ({labels}), so a hard opener is "
            f"a week to sit through rather than a reason to act.")
    if later - now >= 0.6:
        return "worsens", (
            f"This is the kind part of the run ({labels}); it gets harder "
            f"afterwards, which matters more than the single fixture in front "
            f"of him.")
    return "steady", (
        f"The run holds its level over the next four ({labels}), so this week's "
        f"fixture is representative rather than an outlier.")


def keep_or_sell_case(inputs: BriefInputs, direction: str) -> str:
    """Why he stays, expressed as what a transfer would cost.

    A player's place in a squad is not "is he good?" but "is there enough
    wrong with him to spend a transfer removing him?" — a much higher bar,
    and the one the old write-ups never applied.
    """
    if inputs.being_sold:
        return ""
    target = inputs.transfer_alternatives[0] if inputs.transfer_alternatives else None
    fixture = inputs.this_week
    hard_week = bool(fixture and fixture.difficulty >= 3.7)

    if hard_week and direction == "improves":
        return ("Selling him over one difficult fixture would be short-term: "
                "the underlying reasons to own him are unchanged and the run "
                "turns straight afterwards.")
    if target and (target.five_gw or target.delta is not None):
        delta = (target.delta if target.delta is not None
                 else target.five_gw - inputs.five_gw)
        if delta <= 0:
            return (f"The best realistic replacement, {target.name}, projects "
                    f"{abs(delta):.1f} points LOWER over five gameweeks, so "
                    f"there is nothing to move to even if you wanted to.")
        if delta <= 1.0:
            return (f"The best realistic replacement, {target.name}, projects "
                    f"{delta:+.1f} over five gameweeks — not enough to be worth "
                    f"a transfer, so it is better spent elsewhere.")
        if target.rejected_because:
            return (f"{target.name} projects {delta:+.1f} over five gameweeks, "
                    f"and that move was costed and refused — "
                    f"{_shorten(target.rejected_because)}.")
        return (f"{target.name} projects {delta:+.1f} over five gameweeks, which "
                f"is the live argument against keeping him — and it is worth "
                f"revisiting the moment anything is published against him.")
    if inputs.new_club_evidence:
        return ("Nothing published argues for moving him on, so the question "
                "is whether the role holds — that is a thing to watch, not a "
                "thing to spend a transfer on.")
    if inputs.hold_strength >= 65:
        return ("Nothing has changed about why he was bought, and a transfer "
                "spent removing a settled asset is one not available when "
                "something actually goes wrong.")
    return ("There is no case for spending a transfer on him this week, which "
            "is the only question that matters while the squad has bigger "
            "problems.")


def _shorten(reason: str) -> str:
    """The engine's rejection reason, cut to the clause that carries it.

    The full text is written for the transfer page, where it stands
    alone. Quoted inside a verdict it repeated the point the sentence
    around it was already making.
    """
    reason = reason.strip().rstrip(".")
    for separator in (" — ", " -- "):
        if separator in reason:
            reason = reason.split(separator)[0]
    # The engine's reason often opens by restating the projection gap,
    # which the sentence quoting it has just given. Once is enough.
    if " and " in reason and "over five gameweeks" in reason.split(" and ")[0]:
        reason = " and ".join(reason.split(" and ")[1:])
    return reason.strip()


def selection_case(inputs: BriefInputs) -> str:
    """Why he plays instead of the bench, or why he does not.

    Named alternatives, because "he starts" is a statement and "he starts
    ahead of these two, for this reason" is a decision.
    """
    others = inputs.bench_alternatives[:2]
    if not others:
        return ""
    names = " and ".join(o.name for o in others)
    if inputs.on_bench:
        best = others[0]
        verb = "is" if len(others) == 1 else "are"
        detail = f" ({best.detail})" if best.detail else ""
        if len(others) == 1:
            return (f"He sits because {names} {verb} ahead of him on this "
                    f"week's balance of minutes and fixture{detail}.")
        return (f"He sits because {names} {verb} ahead of him on this week's "
                f"balance of minutes and fixture — {best.name} in "
                f"particular{detail}.")
    return (f"He starts ahead of {names}, whose minutes or fixtures are the "
            f"weaker of the options available this week.")


# --- 6. the decision and how much to trust it ----------------------------

def decide(inputs: BriefInputs, playing: str, direction: str) -> tuple[str, str]:
    """A label a manager can act on, and the trade-off behind it."""
    fixture = inputs.this_week
    hard_week = bool(fixture and fixture.difficulty >= 3.7)

    if inputs.being_sold:
        return SELL_NOW, ("The transfer plan moves him on this week — the "
                          "reasoning is in the plan above, not here.")
    if playing == OUT:
        return SELL_IF, ("He cannot play, so the only question is whether the "
                         "replacement is worth a transfer now or after the "
                         "return date is known.")
    if playing == DOUBTFUL:
        return HOLD_REASSESS, ("Too likely to miss out to start, not broken "
                               "enough to sell before the team news lands.")
    if inputs.captain:
        return CAPTAIN_CALL, ("The armband goes to the highest ceiling in the "
                              "squad, and this week that is him.")
    if inputs.vice:
        return VICE_CALL, ("He is the fallback for the armband, which is worth "
                           "more than it looks in a week the captain is doubtful.")

    if inputs.on_bench:
        if playing == UNCERTAIN:
            return BENCH_MONITOR, ("Not enough certainty over his minutes to "
                                   "start him, and not enough wrong with him "
                                   "to spend a transfer.")
        cover = ("secure minutes" if playing == SECURE
                 else "minutes that look likely enough")
        return BENCH_HOLD, (f"A useful body with {cover} is worth having on the "
                            f"bench; he is not the problem with this squad.")

    if playing == UNCERTAIN:
        return START_MONITOR, ("The fixture is worth taking the chance on, but "
                               "his minutes need checking again before the "
                               "deadline.")
    if inputs.new_club_evidence:
        # A summer signing who has started every game is still a signing.
        # Describing him as nailed off a fortnight is exactly the
        # over-claim a transfer is supposed to reset.
        return START_MONITOR, (
            "The fixture is attractive enough to start him, but he is new "
            "enough to the club that the minutes want checking again before "
            "the deadline rather than assuming.")
    if hard_week and direction == "improves":
        return KEEP_THROUGH, ("Accept the harder week rather than spend a "
                              "transfer removing an asset whose run is about "
                              "to turn.")
    if inputs.sell_urgency >= 45:
        return HOLD_REASSESS, ("The concerns are real but unproven; another "
                               "week of evidence decides it either way.")
    return START_HOLD, ("Secure minutes and a fixture worth using outweigh "
                        "what is wrong with him for now.")


def confidence(inputs: BriefInputs, playing: str) -> tuple[str, str]:
    """Earned, not asserted.

    HIGH requires a settled place over a real number of games, no
    contrary reporting, and a club he has been at long enough for any of
    it to mean something. Two starts at a club he has just joined is a
    MEDIUM however clean the numbers look.
    """
    fresh = inputs.status or {}
    if fresh.get("confidence"):
        detail = fresh.get("basis") or "current evidence"
        if fresh.get("stale"):
            detail += ", not recently re-checked"
        return fresh["confidence"], f"resting on {detail}"

    reasons = []
    level = MEDIUM

    if playing in (OUT, DOUBTFUL):
        level = LOW
        reasons.append("his availability is in question")
    elif playing == UNCERTAIN:
        level = LOW if (inputs.new_club_evidence or inputs.injury_evidence) else MEDIUM
        reasons.append("his minutes are not settled")
    elif playing == SECURE and inputs.established:
        level = HIGH
        reasons.append(
            f"a settled place, {inputs.prior_appearances} appearances at the "
            f"club last season behind it")
    elif playing == SECURE and not inputs.thin_sample:
        level = HIGH
        reasons.append(f"a settled place across {_count(inputs.team_games)}")
    elif playing in (SECURE, LIKELY):
        level = MEDIUM
        reasons.append(f"only {_count(inputs.team_games)} of evidence so far")

    if inputs.new_club_evidence and level == HIGH:
        level = MEDIUM
        reasons.append("he is new to the club")
    if inputs.rotation_evidence or inputs.transfer_evidence:
        level = LOW if level == MEDIUM else MEDIUM
        reasons.append("there is reporting that cuts against the raw record")
    return level, "; ".join(reasons)


# --- the assembled brief -------------------------------------------------

@dataclass
class Brief:
    """One player's judgement, in the order a manager reads it."""

    player: str
    why: str = ""
    case_for: str = ""
    against: str = ""
    verdict_label: str = ""
    verdict: str = ""
    next_four: list[str] = field(default_factory=list)
    confidence: str = MEDIUM
    confidence_reason: str = ""
    playing: str = UNCERTAIN
    run: str = "unknown"

    @property
    def words(self) -> int:
        return len(" ".join(
            (self.why, self.case_for, self.against, self.verdict)).split())

    def as_dict(self) -> dict:
        return {"player": self.player, "why": self.why,
                "case_for": self.case_for, "against": self.against,
                "verdict_label": self.verdict_label, "verdict": self.verdict,
                "next_four": self.next_four, "confidence": self.confidence,
                "confidence_reason": self.confidence_reason,
                "playing": self.playing, "run": self.run,
                "words": self.words}


def build(inputs: BriefInputs) -> Brief:
    """Evidence → interpretation → comparison → judgement, in that order.

    Each section has a core that always survives — what he is, whether he
    plays, what the fixture means, the strongest doubt, the decision —
    and optional detail that competes for the remaining words. A brief
    that runs long loses colour; it never loses its conclusion.
    """
    playing, playing_line = playing_verdict(inputs)
    direction, run_line = run_direction(inputs)
    label, rationale = decide(inputs, playing, direction)
    doubts = case_against(inputs, playing)

    sections = {
        # WHY HE'S IN MY TEAM — what he is, and whether he takes the pitch.
        # For a benched player the comparison IS the point: "he sits"
        # is a fact, "he sits because these two are ahead of him" is the
        # decision the reader came for.
        "why": ([_role_line(inputs, playing), playing_line]
                + ([selection_case(inputs)] if inputs.on_bench else [])),
        # THE CASE FOR — the fixture interpreted, and what he does with
        # it. When the numbers give nothing, the access a starter has to
        # the chances is the argument, and it is core: a one-sentence
        # case for is where a write-up stops being an argument.
        "case_for": [fixture_case(inputs)] + (
            [] if (returns_case(inputs) or value_case(inputs)
                   or enabler_case(inputs))
            else [opportunity_case(inputs, playing)]),
        # THE CASE AGAINST — always something, and always about him. Capped
        # at the strongest three: every possible doubt reads as hedging.
        "against": [_sentence_from(_strongest(doubts))],
        # THE VERDICT — the decision, the horizon, and what it trades
        # away. The look-ahead is core: a brief that stops at this week
        # cannot tell a hard fixture from a bad signing, and leaving it to
        # compete for spare words meant a long case-against silently
        # deleted it.
        "verdict": [rationale] + ([run_line] if run_line else []),
    }
    sections = _fill(sections, [
        ("verdict", keep_or_sell_case(inputs, direction)),
        ("case_for", returns_case(inputs)),
        ("case_for", opportunity_case(inputs, playing)),
        ("why", "" if inputs.on_bench else selection_case(inputs)),
        ("case_for", value_case(inputs)),
        ("case_for", enabler_case(inputs)),
    ], budget=MAX_WORDS)

    level, why_that = confidence(inputs, playing)
    return Brief(
        player=inputs.player,
        why=" ".join(sections["why"]), case_for=" ".join(sections["case_for"]),
        against=" ".join(sections["against"]),
        verdict_label=label, verdict=" ".join(sections["verdict"]),
        next_four=[f.label for f in inputs.fixtures[:4]],
        confidence=level, confidence_reason=why_that,
        playing=playing, run=direction)


def enabler_case(inputs: BriefInputs) -> str:
    """The quiet job a cheap player does: holding money somewhere else.

    A £4.0m defender is not bought to score. Judging him as though he
    were is how a squad's cheapest slots get churned for no gain.
    """
    if inputs.price > 4.6 or inputs.five_gw >= inputs.positional_five_gw:
        return ""
    if inputs.on_bench:
        return (f"At £{inputs.price:.1f}m his job is to be a legal body who "
                f"frees money for the rest of the squad, and he does that "
                f"whether or not he plays.")
    return (f"At £{inputs.price:.1f}m he is priced as an enabler, so the bar "
            f"he has to clear is being playable rather than being good.")


def _role_line(inputs: BriefInputs, playing: str) -> str:
    """What he is in this squad, in a manager's words rather than a label."""
    where = "on the bench" if inputs.on_bench else "in the eleven"
    if inputs.captain:
        where = "captain"
    elif inputs.vice:
        where = "vice-captain"
    descriptor = {
        "GKP": "goalkeeper", "DEF": "defender",
        "MID": "midfielder", "FWD": "forward",
    }.get(inputs.position, "player")
    if playing in (SECURE, LIKELY) and not inputs.on_bench:
        descriptor = f"{'nailed' if playing == SECURE else 'first-choice'} {descriptor}"
    return (f"{inputs.player} is {_article(inputs.price)} "
            f"£{inputs.price:.1f}m {inputs.club_name or inputs.club} "
            f"{descriptor}, "
            f"{'the ' if where in ('captain', 'vice-captain') else ''}{where} "
            f"this week.")


DOUBT_BUDGET = 46


def _strongest(doubts: list[str]) -> list[str]:
    """The doubts worth the room, in the order they were raised.

    Capped by words rather than by count. Three sentences of caveat read
    as hedging, and on one player they grew long enough to push the
    look-ahead off the end of the write-up entirely.
    """
    kept, used = [], 0
    for doubt in doubts:
        cost = len(doubt.split())
        if kept and used + cost > DOUBT_BUDGET:
            break
        kept.append(doubt)
        used += cost
    return kept


def _sentence_from(parts: list[str]) -> str:
    """Turns a list of doubts into prose rather than a bullet list."""
    parts = [p.rstrip(".") for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return _capitalise(parts[0]) + "."
    lead = _capitalise(parts[0])
    rest = parts[1:3]
    if len(rest) == 1:
        return f"{lead}, and {rest[0]}."
    return f"{lead}. On top of that, {rest[0]}, and {rest[1]}."


def _capitalise(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


MIN_WORDS, MAX_WORDS = 100, 180


def _fill(sections: dict, optional: list[tuple], budget: int) -> dict:
    """Core sentences always survive; optional ones compete for what is left.

    Budgeting globally rather than per section is what keeps the
    three-to-five gameweek look-ahead on the page. A per-section cap kept
    trimming it off the end of the verdict — the one sentence that says
    whether a hard fixture is a week to sit through or the start of a
    trend, cut to make room for a sentence about expected assists.

    `optional` is ordered by how much the reader would miss it.
    """
    used = sum(len(" ".join(v).split()) for v in sections.values())
    for key, sentence in optional:
        if not sentence:
            continue
        cost = len(sentence.split())
        if used + cost > budget:
            continue
        sections[key].append(sentence)
        used += cost
    return sections


def _role_line(inputs: BriefInputs, playing: str) -> str:
    """What he is in this squad, in a manager's words rather than a label."""
    where = "on the bench" if inputs.on_bench else "in the eleven"
    if inputs.captain:
        where = "captain"
    elif inputs.vice:
        where = "vice-captain"
    descriptor = {
        "GKP": "goalkeeper", "DEF": "defender",
        "MID": "midfielder", "FWD": "forward",
    }.get(inputs.position, "player")
    if playing in (SECURE, LIKELY) and not inputs.on_bench:
        descriptor = f"{'nailed' if playing == SECURE else 'first-choice'} {descriptor}"
    return (f"{inputs.player} is {_article(inputs.price)} "
            f"£{inputs.price:.1f}m {inputs.club_name or inputs.club} "
            f"{descriptor}, "
            f"{'the ' if where in ('captain', 'vice-captain') else ''}{where} "
            f"this week.")


DOUBT_BUDGET = 46


def _strongest(doubts: list[str]) -> list[str]:
    """The doubts worth the room, in the order they were raised.

    Capped by words rather than by count. Three sentences of caveat read
    as hedging, and on one player they grew long enough to push the
    look-ahead off the end of the write-up entirely.
    """
    kept, used = [], 0
    for doubt in doubts:
        cost = len(doubt.split())
        if kept and used + cost > DOUBT_BUDGET:
            break
        kept.append(doubt)
        used += cost
    return kept


def _sentence_from(parts: list[str]) -> str:
    """Turns a list of doubts into prose rather than a bullet list."""
    parts = [p.rstrip(".") for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return _capitalise(parts[0]) + "."
    lead = _capitalise(parts[0])
    rest = parts[1:3]
    if len(rest) == 1:
        return f"{lead}, and {rest[0]}."
    return f"{lead}. On top of that, {rest[0]}, and {rest[1]}."


def _capitalise(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


MIN_WORDS, MAX_WORDS = 100, 180


def _assemble(core: list[str], optional: list[str], budget: int) -> str:
    """Core sentences always survive; optional ones fill what is left.

    The earlier version trimmed whole sections from the end, which took
    the playing verdict out of "why he's in my team" and left a paragraph
    naming a hard fixture with no mention of the strong defence that
    makes it survivable. Losing the point is not a length fix.
    """
    kept = [s for s in core if s]
    used = sum(len(s.split()) for s in kept)
    for sentence in optional:
        if not sentence:
            continue
        cost = len(sentence.split())
        if used + cost > budget:
            continue
        kept.append(sentence)
        used += cost
    return " ".join(kept)

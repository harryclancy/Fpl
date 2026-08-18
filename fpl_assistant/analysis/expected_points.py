"""Expected points (xP): projects how many FPL points each player will
actually score, gameweek by gameweek.

This replaces the old 0-1 `squad_score` as the currency of the selection
engine, and the change of units is the whole point. A normalised score can
only rank players; it can't tell you that a £13.0m striker projected at 6.4
points is worth two £6.5m midfielders at 3.1 each, because the numbers
aren't on a scale where arithmetic means anything. Points are, so the
optimiser downstream can trade price against output honestly.

The model is bottom-up: rebuild each scoring category from the underlying
rate that drives it, then multiply by how much the player is actually
expected to be on the pitch.

    xP = appearance + goals + assists + clean sheet + saves
         + defensive contributions + bonus - goals conceded - cards

Two deliberate choices worth knowing about:

1. Rates, not totals. Everything keys off per-90 numbers multiplied by
   expected minutes. Season cumulative totals reward a player for merely
   having played more games, which silently double-counts availability --
   we want "good per minute" and "plays a lot" as separate, explicit terms
   so a nailed-on starter beats an equally-talented rotation risk for the
   right reason.

2. Underlying, not realised. Expected goals drive the projection rather
   than goals actually scored, because finishing over a handful of games is
   mostly noise while shot volume and quality persist. That's the single
   biggest edge a model has over a league table.

Everything is blended against the player's own realised points-per-game as
a sanity anchor (see POINTS_MODEL_WEIGHT) so a mis-specified component
can't drag a demonstrably productive player down too far.
"""
import numpy as np
import pandas as pd

from fpl_assistant.analysis.season_state import is_preseason

# --- FPL scoring rules -------------------------------------------------
GOAL_POINTS = {"GKP": 6, "DEF": 6, "MID": 5, "FWD": 4}
CLEAN_SHEET_POINTS = {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}
ASSIST_POINTS = 3
SAVES_PER_POINT = 3
GOALS_CONCEDED_PER_MINUS_ONE = 2
# Lowest credible expected goals-conceded per match. Calibrated against
# reality rather than picked for convenience: the best Premier League
# defences concede about 0.75 a game across a season (a title-winning side
# lands near 29 goals in 38), and the league averages roughly 1.4. Poisson
# P(0) turns those into clean-sheet rates of ~47% and ~25% respectively,
# which is what actually happens. A floor much below this quietly hands
# every defender a coin-flip clean sheet.
MIN_EXPECTED_CONCEDED = 0.70
# Defensive contributions (clearances/blocks/interceptions/tackles) award 2
# points at a per-position threshold. The API reports the count a player has
# already banked, so we model it as an empirical per-game rate rather than
# trying to reconstruct the threshold logic.
DEFENSIVE_CONTRIBUTION_POINTS = 2

# --- Model parameters --------------------------------------------------
FULL_MATCH_MINUTES = 90
SIXTY_MINUTE_THRESHOLD = 60
# A player who starts averages a bit under 90 once substitutions are
# accounted for; one who doesn't start but does appear gets a short cameo.
STARTER_MINUTES = 82.0
CAMEO_MINUTES = 18.0

# Weight on the bottom-up component model vs. the player's realised
# points-per-game. The component model should lead -- it's built on
# underlying rates that predict better than past returns -- but anchoring
# partly on what a player has actually delivered hedges against any single
# component being mis-specified.
POINTS_MODEL_WEIGHT = 0.65

# Later gameweeks are worth less to a decision made today: you get to make
# transfers before then, so a great fixture four weeks out is worth far less
# than one this weekend. Each subsequent gameweek is discounted by this
# factor.
HORIZON_DECAY = 0.84
DEFAULT_HORIZON = 5

# Penalty duty uplift, in expected goals per 90. Applied additively to the
# designated taker. This slightly double-counts for an established taker
# whose per-90 xG already includes penalties they've taken -- but it
# corrects a much larger under-rating for a *newly* appointed taker and
# during the early-season window when per-90 samples are thin and noisy.
# Deliberately modest for that reason, and it decays as real minutes
# accumulate (see _penalty_uplift).
PENALTY_XG_UPLIFT = {1: 0.11, 2: 0.03}
# First-choice set-piece delivery is a real, persistent assist driver.
SET_PIECE_XA_UPLIFT = {1: 0.05, 2: 0.02}

# League-average baselines, used to convert FPL's team strength ratings into
# a multiplier and to fall back sensibly when data is missing.
BASELINE_TEAM_STRENGTH = 1100.0
# How hard fixture quality swings the projection. 1.0 would mean a team
# rated twice as strong defensively halves the opposing striker's output,
# which overstates it; football is noisier than that.
FIXTURE_ELASTICITY = 0.55
MAX_FIXTURE_MULTIPLIER = 1.45
MIN_FIXTURE_MULTIPLIER = 0.60
HOME_ADVANTAGE = 1.08

# Captaincy is not the same decision as selection, so it doesn't rank on
# the same number. The armband doubles a score, which means what you want
# is the highest *ceiling*, not the highest mean -- and those come apart by
# position. A defender and a striker projected at the same 5.0 points have
# very different upside: the striker can return 20+ on a two-goal
# afternoon, while the defender's realistic best is a clean sheet, a bonus
# haul and maybe a goal. Doubling the striker is worth more even when the
# means are identical, so captaincy scores are discounted by position
# ceiling before ranking.
CAPTAIN_CEILING_FACTOR = {"FWD": 1.00, "MID": 0.97, "DEF": 0.80, "GKP": 0.68}

# Preseason, every rate stat is zero, so the model has nothing to chew on.
# Price is the best available prior: FPL's pricing algorithm is itself a
# points forecast, set by people with access to far more data than the
# public API exposes.
#
# The *shape* of that curve matters enormously, and getting it wrong is
# not a small calibration error -- it breaks the optimiser outright. A
# linear prior (points = a·price + b) makes the objective degenerate:
# summed over a fixed number of slots, total points depend only on total
# spend, not on how that spend is distributed. Every way of allocating
# £84m across eleven players scores identically, so the solver becomes
# indifferent between a squad built around a £15.0m striker and one
# spreading the same money evenly, and the choice falls to whichever
# tie-breaker happens to be largest. That is exactly how a near-unanimous
# premium ends up excluded for no stateable reason.
#
# Real returns are concave -- each extra million buys less than the last --
# which restores a genuine trade-off. Fitted logarithmically against how
# FPL prices translate to points in practice:
#   £4.0m -> ~2.0/game (fringe, often not starting)
#   £7.0m -> ~4.0      £11.0m -> ~5.7
#   £15.0m -> ~6.8     (elite, nailed on)
# Premiums then earn their place through the captaincy term rather than
# through a spurious linear value edge, which is the real-world argument
# for them.
PRESEASON_LOG_SLOPE = 3.63
PRESEASON_LOG_INTERCEPT = -3.03
PRESEASON_MIN_PRICE = 3.9  # guards log() against nonsense inputs
# Ownership is a weaker but real second signal preseason -- it aggregates
# the research of millions of managers, which is informative even though
# it also carries herd behaviour.
PRESEASON_OWNERSHIP_BONUS = 0.9


def _safe_div(numerator, denominator, default=0.0):
    """Element-wise divide that yields `default` instead of inf/NaN."""
    result = np.divide(
        numerator,
        denominator,
        out=np.full_like(np.asarray(numerator, dtype=float), float(default)),
        where=np.asarray(denominator, dtype=float) != 0,
    )
    return result


def team_schedule(
    fixtures: pd.DataFrame, from_event: int, horizon: int
) -> dict[int, dict[int, list[tuple[int, bool]]]]:
    """Maps team_id -> gameweek -> list of (opponent_id, is_home).

    A list per gameweek rather than a single fixture because double
    gameweeks are exactly where the biggest points swings live, and
    averaging them (as a difficulty table does) throws that away -- two
    fixtures is close to two chances to score, so they need to be summed.
    An empty list is a blank gameweek: genuinely zero points, not neutral.
    """
    window = fixtures[
        fixtures["event"].notna()
        & (fixtures["event"] >= from_event)
        & (fixtures["event"] < from_event + horizon)
    ]

    schedule: dict[int, dict[int, list[tuple[int, bool]]]] = {}
    for _, fx in window.iterrows():
        gw = int(fx["event"])
        home, away = int(fx["team_h"]), int(fx["team_a"])
        schedule.setdefault(home, {}).setdefault(gw, []).append((away, True))
        schedule.setdefault(away, {}).setdefault(gw, []).append((home, False))
    return schedule


def _strength(teams: pd.DataFrame, column: str) -> pd.Series:
    """One team-strength column, with the league mean substituted wherever
    the API didn't supply a usable value."""
    if column not in teams.columns:
        return pd.Series(BASELINE_TEAM_STRENGTH, index=teams.index, dtype=float)
    values = pd.to_numeric(teams[column], errors="coerce")
    if values.notna().sum() == 0:
        return pd.Series(BASELINE_TEAM_STRENGTH, index=teams.index, dtype=float)
    return values.fillna(values.mean()).astype(float)


def _fixture_multipliers(teams: pd.DataFrame) -> dict[str, pd.Series]:
    """Per-opponent multipliers for attacking output and for clean sheets.

    Directional on purpose: a striker's fixture is easy when the opponent
    *defends* badly; a defender's is easy when the opponent *attacks*
    badly. Collapsing both into one difficulty number (as the 1-5 FDR does)
    means a team that both leaks and scores freely reads as equally easy for
    everyone, which is wrong in opposite directions for the two groups.
    """
    attack_home = _strength(teams, "strength_attack_home")
    attack_away = _strength(teams, "strength_attack_away")
    defence_home = _strength(teams, "strength_defence_home")
    defence_away = _strength(teams, "strength_defence_away")

    opponent_defence = (defence_home + defence_away) / 2.0
    opponent_attack = (attack_home + attack_away) / 2.0

    def to_multiplier(strength: pd.Series, mean: float) -> pd.Series:
        # Weaker opponent (lower strength) -> multiplier above 1.
        raw = (mean / strength.replace(0, np.nan)) ** FIXTURE_ELASTICITY
        return raw.fillna(1.0).clip(MIN_FIXTURE_MULTIPLIER, MAX_FIXTURE_MULTIPLIER)

    return {
        # Facing a weak defence boosts a player's attacking returns.
        "attack": to_multiplier(opponent_defence, opponent_defence.mean()),
        # Facing a weak attack boosts your side's clean-sheet chances.
        "defence": to_multiplier(opponent_attack, opponent_attack.mean()),
    }


def _games_played(players: pd.DataFrame, from_event: int) -> float:
    """How many gameweeks of data the per-game rates are drawn from.

    Derived from the most-used player's minutes rather than the gameweek
    number, because the gameweek counter runs ahead of matches actually
    played (and a team can have a game in hand).
    """
    if players.empty:
        return 1.0
    by_minutes = players["minutes"].fillna(0).max() / FULL_MATCH_MINUTES
    by_event = max(from_event - 1, 0)
    return max(1.0, min(by_event, np.ceil(by_minutes)) if by_event else np.ceil(by_minutes))


def _availability(players: pd.DataFrame) -> pd.Series:
    """Probability the player is fit and selectable at all.

    `status` is the hard signal (injured/suspended/on loan = 0) and
    `chance_of_playing_next_round` the graded one. Both matter: a player can
    be flagged 'd' (doubtful) at 75% and still be worth owning, while an 'i'
    is worth exactly nothing this week no matter how good their rates are.
    """
    unavailable = players["status"].isin(["i", "s", "u", "n"])
    chance = pd.to_numeric(
        players.get("chance_of_playing_next_round", 100), errors="coerce"
    ).fillna(100.0) / 100.0
    return chance.clip(0.0, 1.0).mask(unavailable, 0.0)


def _start_probability(players: pd.DataFrame, games: float, preseason: bool) -> pd.Series:
    """Probability the player starts, given they're available.

    This is the signal the old scoring formula was missing entirely, and
    it's arguably the most important one in FPL: a player who doesn't play
    scores zero regardless of how good they are. `starts` measures
    nailed-on-ness directly; minutes-per-game is the fallback when it isn't
    reported.
    """
    if preseason:
        # No appearances to learn from. Price is the best available proxy
        # for "will they be in the first XI" -- expensive players are
        # expensive largely because they're expected to play.
        price_rank = players["price"].rank(pct=True)
        return (0.55 + 0.40 * price_rank).clip(0.0, 1.0)

    starts = pd.to_numeric(players.get("starts", 0), errors="coerce").fillna(0)
    start_rate = (starts / games).clip(0.0, 1.0)

    # Where `starts` is absent or zero for everyone, fall back to how much
    # of the available minutes they've actually played.
    minutes_share = (players["minutes"].fillna(0) / (games * FULL_MATCH_MINUTES)).clip(0.0, 1.0)
    return start_rate.where(start_rate > 0, minutes_share)


def _expected_minutes(p_available: pd.Series, p_start: pd.Series) -> pd.Series:
    """Expected minutes in a single match."""
    starting = p_available * p_start
    cameo = p_available * (1 - p_start) * 0.45  # not every non-starter gets on
    return starting * STARTER_MINUTES + cameo * CAMEO_MINUTES


def _penalty_uplift(players: pd.DataFrame, games: float, preseason: bool) -> pd.Series:
    """Extra expected goals per 90 for the designated penalty taker.

    Tapered by how much real data we have: with a full season of minutes a
    player's own per-90 xG already reflects the penalties they take, so the
    uplift shrinks toward zero to avoid double-counting. Early on -- or for
    a taker who has just inherited the job -- it's the only thing carrying
    that information.
    """
    order = pd.to_numeric(players.get("penalties_order", pd.NA), errors="coerce")
    uplift = order.map(PENALTY_XG_UPLIFT).fillna(0.0).astype(float)
    if preseason:
        return uplift
    # Full weight for the first ~6 games of evidence, fading to ~0 by ~20.
    taper = float(np.clip((20.0 - games) / 14.0, 0.0, 1.0))
    return uplift * taper


def _set_piece_uplift(players: pd.DataFrame) -> pd.Series:
    """Extra expected assists per 90 for first-choice dead-ball delivery."""
    corners = pd.to_numeric(
        players.get("corners_and_indirect_freekicks_order", pd.NA), errors="coerce"
    )
    freekicks = pd.to_numeric(players.get("direct_freekicks_order", pd.NA), errors="coerce")
    best = pd.concat([corners, freekicks], axis=1).min(axis=1)
    return best.map(SET_PIECE_XA_UPLIFT).fillna(0.0).astype(float)


def _preseason_base_points(players: pd.DataFrame) -> pd.Series:
    """Points-per-match prior for when no match data exists yet.

    Anchored on price, because FPL's own pricing is a points forecast made
    with better information than the public API carries, and nudged by
    ownership as a second opinion from the wider manager base.
    """
    price = players["price"].clip(lower=PRESEASON_MIN_PRICE)
    price_component = PRESEASON_LOG_INTERCEPT + PRESEASON_LOG_SLOPE * np.log(price)
    ownership = pd.to_numeric(players.get("selected_by_percent", 0), errors="coerce").fillna(0.0)
    ownership_component = PRESEASON_OWNERSHIP_BONUS * (ownership / 100.0)
    return (price_component + ownership_component).clip(lower=0.3)


def _component_points_per_match(
    players: pd.DataFrame,
    xmins: pd.Series,
    p_sixty: pd.Series,
    attack_mult: pd.Series,
    defence_mult: pd.Series,
    games: float,
    preseason: bool,
) -> pd.Series:
    """The bottom-up expected points for one match, before blending."""
    minutes_share = xmins / FULL_MATCH_MINUTES
    position = players["position"]

    if preseason:
        base = _preseason_base_points(players)
        # Even without rate data, fixture quality still applies -- and it
        # applies directionally by position, same as in-season.
        is_attacking = position.isin(["MID", "FWD"])
        multiplier = attack_mult.where(is_attacking, defence_mult)
        return base * multiplier

    # --- Attacking returns ---
    xg90 = pd.to_numeric(players.get("expected_goals_per_90", 0), errors="coerce").fillna(0.0)
    xa90 = pd.to_numeric(players.get("expected_assists_per_90", 0), errors="coerce").fillna(0.0)

    # Where per-90 columns are missing entirely, derive them from the season
    # cumulative involvement so the model still has an attacking signal.
    if xg90.sum() == 0 and xa90.sum() == 0:
        xgi = pd.to_numeric(
            players.get("expected_goal_involvements", 0), errors="coerce"
        ).fillna(0.0)
        per_90 = pd.Series(
            _safe_div(xgi.to_numpy(), (players["minutes"].fillna(0) / FULL_MATCH_MINUTES).to_numpy()),
            index=players.index,
        )
        xg90, xa90 = per_90 * 0.6, per_90 * 0.4

    xg90 = xg90 + _penalty_uplift(players, games, preseason)
    xa90 = xa90 + _set_piece_uplift(players)

    goal_value = position.map(GOAL_POINTS).fillna(4).astype(float)
    attacking = (
        xg90 * goal_value + xa90 * ASSIST_POINTS
    ) * minutes_share * attack_mult

    # --- Clean sheets and goals conceded ---
    xgc90 = pd.to_numeric(
        players.get("expected_goals_conceded_per_90", 0), errors="coerce"
    ).fillna(0.0)
    if xgc90.sum() == 0:
        xgc_total = pd.to_numeric(
            players.get("expected_goals_conceded", 0), errors="coerce"
        ).fillna(0.0)
        xgc90 = pd.Series(
            _safe_div(
                xgc_total.to_numpy(),
                (players["minutes"].fillna(0) / FULL_MATCH_MINUTES).to_numpy(),
            ),
            index=players.index,
        )

    # Goals against follow a Poisson process closely enough that P(0) =
    # exp(-expected goals) is a good clean-sheet estimate. Dividing the
    # multiplier through reflects that a weak opponent attack lowers the
    # expected concession.
    #
    # The floor matters more than it looks. Even the best Premier League
    # defences concede around 0.7 goals a game across a season, so an
    # expected-concession near zero is never real -- it means the input was
    # missing, mis-scaled, or drawn from too few matches. Without a
    # realistic floor those cases produce clean-sheet probabilities above
    # 90%, which inflates every defender and goalkeeper enough to push them
    # past forwards in the projection (and, worse, into the captaincy pick).
    expected_conceded = (xgc90 / defence_mult.replace(0, 1.0)).clip(lower=MIN_EXPECTED_CONCEDED)
    p_clean_sheet = np.exp(-expected_conceded)

    cs_value = position.map(CLEAN_SHEET_POINTS).fillna(0).astype(float)
    # Clean-sheet points require 60 minutes on the pitch.
    clean_sheet = p_clean_sheet * cs_value * p_sixty

    concedes_penalty = pd.Series(0.0, index=players.index)
    is_defensive = position.isin(["GKP", "DEF"])
    concedes_penalty = concedes_penalty.mask(
        is_defensive, expected_conceded / GOALS_CONCEDED_PER_MINUS_ONE * p_sixty
    )

    # --- Saves (goalkeepers) ---
    saves90 = pd.to_numeric(players.get("saves_per_90", 0), errors="coerce").fillna(0.0)
    if saves90.sum() == 0:
        saves_total = pd.to_numeric(players.get("saves", 0), errors="coerce").fillna(0.0)
        saves90 = pd.Series(
            _safe_div(
                saves_total.to_numpy(),
                (players["minutes"].fillna(0) / FULL_MATCH_MINUTES).to_numpy(),
            ),
            index=players.index,
        )
    saves = (saves90 * minutes_share / SAVES_PER_POINT).where(position == "GKP", 0.0)

    # --- Defensive contributions (2025/26 onward) ---
    # The threshold can only be met once per match, so the rate is capped at
    # 1.0 regardless of what the field turns out to count. Worth being
    # explicit about: the API has reported this stat inconsistently across
    # seasons (raw actions vs. times the threshold was hit), and reading a
    # raw-action count as threshold-hits would silently inflate every
    # defender by several points a game.
    defcon_rate = (
        pd.to_numeric(players.get("defensive_contribution", 0), errors="coerce").fillna(0.0) / games
    ).clip(upper=1.0)
    defensive_contribution = defcon_rate * minutes_share * DEFENSIVE_CONTRIBUTION_POINTS

    # --- Bonus ---
    # Modelled empirically from bonus already earned rather than from BPS
    # thresholds: who collects bonus is highly persistent (it tracks goals,
    # assists, clean sheets and defensive actions), so the realised rate is
    # a good forecast and avoids reimplementing the whole BPS table.
    bonus_rate = pd.to_numeric(players.get("bonus", 0), errors="coerce").fillna(0.0) / games
    bonus = bonus_rate * minutes_share

    # --- Cards ---
    yellows = pd.to_numeric(players.get("yellow_cards", 0), errors="coerce").fillna(0.0) / games
    reds = pd.to_numeric(players.get("red_cards", 0), errors="coerce").fillna(0.0) / games
    cards = (yellows + 3 * reds) * minutes_share

    # --- Appearance ---
    appearance = 2 * p_sixty + 1 * (xmins > 0).astype(float) * (1 - p_sixty)

    return (
        appearance
        + attacking
        + clean_sheet
        + saves
        + defensive_contribution
        + bonus
        - concedes_penalty
        - cards
    )


def expected_points(
    players: pd.DataFrame,
    fixtures: pd.DataFrame,
    teams: pd.DataFrame,
    from_event: int,
    horizon: int = DEFAULT_HORIZON,
) -> pd.DataFrame:
    """Projects expected FPL points per player.

    Adds:
      `xp_next`     — expected points in the next gameweek (drives captaincy)
      `xp_horizon`  — decayed sum over the horizon (drives squad selection)
      `xp_per_match`, `expected_minutes`, `p_start`, `p_available`
      `fixture_multiplier` — average attacking fixture swing over the horizon

    Unavailable players are kept in the frame with an xP near zero rather
    than dropped, so callers can still explain *why* someone isn't picked.
    """
    df = players.copy()
    preseason = is_preseason(players)
    games = _games_played(players, from_event)

    multipliers = _fixture_multipliers(teams)
    schedule = team_schedule(fixtures, from_event, horizon)

    p_available = _availability(df)
    p_start = _start_probability(df, games, preseason)
    xmins = _expected_minutes(p_available, p_start)
    # Playing 60+ minutes is essentially "started and wasn't hooked early".
    p_sixty = (p_available * p_start * 0.88).clip(0.0, 1.0)

    df["p_available"] = p_available.round(3)
    df["p_start"] = p_start.round(3)
    df["expected_minutes"] = xmins.round(1)

    gameweeks = list(range(from_event, from_event + horizon))
    per_gw_points: dict[int, pd.Series] = {}
    per_gw_attack_mult: dict[int, pd.Series] = {}

    for gw in gameweeks:
        # Build this gameweek's per-player fixture multipliers by looking up
        # each player's team's opponent(s). Doubles sum, blanks score zero.
        attack_acc = pd.Series(0.0, index=df.index)
        defence_acc = pd.Series(0.0, index=df.index)
        fixture_count = pd.Series(0.0, index=df.index)

        for team_id, gw_map in schedule.items():
            entries = gw_map.get(gw, [])
            if not entries:
                continue
            mask = df["team"] == team_id
            if not mask.any():
                continue
            for opponent_id, is_home in entries:
                venue = HOME_ADVANTAGE if is_home else 1.0 / HOME_ADVANTAGE
                atk = float(multipliers["attack"].get(opponent_id, 1.0)) * venue
                dfc = float(multipliers["defence"].get(opponent_id, 1.0)) * venue
                attack_acc = attack_acc.mask(mask, attack_acc + atk)
                defence_acc = defence_acc.mask(mask, defence_acc + dfc)
                fixture_count = fixture_count.mask(mask, fixture_count + 1)

        played = fixture_count > 0
        # Average multiplier across the gameweek's fixtures...
        mean_attack = pd.Series(
            _safe_div(attack_acc.to_numpy(), fixture_count.to_numpy(), default=1.0), index=df.index
        )
        mean_defence = pd.Series(
            _safe_div(defence_acc.to_numpy(), fixture_count.to_numpy(), default=1.0), index=df.index
        )

        gw_points = _component_points_per_match(
            df, xmins, p_sixty, mean_attack, mean_defence, games, preseason
        )
        # ...then scale by how many fixtures they actually have. A double
        # gameweek is close to two independent chances to score; a blank is
        # zero, not "average".
        gw_points = gw_points * fixture_count
        per_gw_points[gw] = gw_points.where(played, 0.0)
        per_gw_attack_mult[gw] = mean_attack.where(played, 0.0)

    # Blend the component model against realised points-per-game, which acts
    # as a sanity anchor. Skipped preseason, where points-per-game is zero
    # for everyone and would just drag every projection toward nothing.
    if not preseason:
        ppg = pd.to_numeric(df.get("points_per_game", 0), errors="coerce").fillna(0.0)
        # Points-per-game is only meaningful for players who have actually
        # featured; for the rest it's zero for lack of chances, not lack of
        # ability, so lean fully on the component model there.
        has_record = df["minutes"].fillna(0) >= FULL_MATCH_MINUTES
        # Points-per-game is points per game *they featured in*, so it has
        # to be rescaled by how much they're expected to feature now.
        # Applying it raw lets a player who starred in two games and then
        # lost his place keep the full rate forever -- which is how a
        # £13.0m player projected to play 15 minutes ended up with a
        # starter's projection and a place in the recommended XI.
        availability_scale = (xmins / STARTER_MINUTES).clip(0.0, 1.0)
        for gw in gameweeks:
            anchor = ppg * availability_scale * (per_gw_points[gw] > 0).astype(float)
            blended = POINTS_MODEL_WEIGHT * per_gw_points[gw] + (1 - POINTS_MODEL_WEIGHT) * anchor
            per_gw_points[gw] = blended.where(has_record, per_gw_points[gw])

    for offset, gw in enumerate(gameweeks):
        df[f"xp_gw{gw}"] = per_gw_points[gw].round(2)

    df["xp_next"] = per_gw_points[gameweeks[0]].round(2) if gameweeks else 0.0
    df["xp_horizon"] = (
        sum(per_gw_points[gw] * (HORIZON_DECAY**offset) for offset, gw in enumerate(gameweeks))
        if gameweeks
        else pd.Series(0.0, index=df.index)
    ).round(3)
    df["xp_per_match"] = (
        df["xp_horizon"] / sum(HORIZON_DECAY**i for i in range(len(gameweeks)))
    ).round(2) if gameweeks else 0.0

    fixture_mult_mean = (
        sum(per_gw_attack_mult[gw] for gw in gameweeks) / len(gameweeks)
        if gameweeks
        else pd.Series(1.0, index=df.index)
    )
    df["fixture_multiplier"] = fixture_mult_mean.round(3)
    df["xp_basis"] = "preseason" if preseason else "form"

    # Ceiling-adjusted score for the armband decision only -- never for
    # selection, where the mean is the right thing to maximise.
    ceiling = df["position"].map(CAPTAIN_CEILING_FACTOR).fillna(0.9).astype(float)
    df["xp_captain"] = (df["xp_next"] * ceiling).round(2)

    # Value framing: points per million is what actually decides whether a
    # premium is worth its price tag once the budget constraint bites.
    df["xp_per_million"] = (df["xp_horizon"] / df["price"]).round(3)

    return df
